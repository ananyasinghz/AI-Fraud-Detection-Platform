"""Immutable ULB ingestion and duplicate-group-safe partitioning."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import Field, model_validator
from sklearn.model_selection import train_test_split

from backend.app.domain.base import ContractModel
from backend.app.ml.schema import (
    RAW_FEATURES,
    DatasetValidationError,
    RawDatasetSummary,
    sha256_file,
    validate_raw_dataset,
)


class SplitConfig(ContractModel):
    version: str
    seed: int = Field(ge=0)
    train_ratio: float = Field(gt=0, lt=1)
    validation_ratio: float = Field(gt=0, lt=1)
    test_ratio: float = Field(gt=0, lt=1)
    expected_rows: int | None = Field(default=None, ge=1)
    expected_fraud_rows: int | None = Field(default=None, ge=1)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    grouping: str

    @model_validator(mode="after")
    def validate_ratios(self) -> "SplitConfig":
        total = self.train_ratio + self.validation_ratio + self.test_ratio
        if abs(total - 1.0) > 1e-9:
            raise ValueError("split ratios must sum to 1")
        return self


class SplitManifest(ContractModel):
    version: str
    seed: int
    raw_sha256: str
    assignment_sha256: str
    source_rows: int
    source_fraud_rows: int
    feature_groups: int
    duplicate_rows: int
    partition_rows: dict[str, int]
    partition_fraud_rows: dict[str, int]
    files: dict[str, str]


class PreparationResult(ContractModel):
    raw_summary: RawDatasetSummary
    manifest: SplitManifest
    raw_copy_created: bool


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return value


def load_split_config(path: Path) -> SplitConfig:
    return SplitConfig.model_validate(_read_yaml(path))


def copy_immutable_source(source: Path, destination: Path) -> bool:
    """Copy once and reject changes to either side."""
    if not source.is_file():
        raise FileNotFoundError(source)
    source_hash = sha256_file(source)
    if destination.exists():
        destination_hash = sha256_file(destination)
        if destination_hash != source_hash:
            raise DatasetValidationError(
                "immutable raw copy differs from source; remove neither file until reviewed"
            )
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sha256_file(destination) != source_hash:
        destination.unlink(missing_ok=True)
        raise OSError("raw copy verification failed")
    return True


def _partition_groups(
    frame: pd.DataFrame,
    config: SplitConfig,
) -> pd.DataFrame:
    group_ids = frame.groupby(list(RAW_FEATURES), sort=True, dropna=False).ngroup()
    working = frame.assign(_group_id=group_ids)
    label_counts = working.groupby("_group_id", sort=True)["Class"].nunique()
    conflicting = label_counts[label_counts > 1]
    if not conflicting.empty:
        raise DatasetValidationError("identical feature rows have conflicting Class labels")
    groups = (
        working.groupby("_group_id", sort=True)
        .agg(label=("Class", "first"), row_count=("Class", "size"))
        .reset_index()
    )
    train_ids, remainder_ids = train_test_split(
        groups["_group_id"],
        test_size=config.validation_ratio + config.test_ratio,
        random_state=config.seed,
        stratify=groups["label"],
    )
    remainder = groups[groups["_group_id"].isin(remainder_ids)]
    validation_fraction = config.validation_ratio / (config.validation_ratio + config.test_ratio)
    validation_ids, test_ids = train_test_split(
        remainder["_group_id"],
        train_size=validation_fraction,
        random_state=config.seed,
        stratify=remainder["label"],
    )
    partition_by_group = {
        **{int(group_id): "train" for group_id in train_ids},
        **{int(group_id): "validation" for group_id in validation_ids},
        **{int(group_id): "test" for group_id in test_ids},
    }
    assignments = pd.DataFrame(
        {
            "row_index": frame.index.astype(int),
            "group_id": group_ids.astype(int),
            "partition": group_ids.map(partition_by_group),
        }
    )
    if assignments["partition"].isna().any():
        raise RuntimeError("some duplicate groups were not assigned")
    if assignments.groupby("group_id")["partition"].nunique().max() != 1:
        raise RuntimeError("a duplicate group crossed partitions")
    return assignments


def _assignment_hash(assignments: pd.DataFrame) -> str:
    content = assignments.to_csv(index=False, lineterminator="\n").encode()
    return hashlib.sha256(content).hexdigest()


def prepare_ml_data(
    *,
    source_path: Path,
    raw_copy_path: Path,
    split_dir: Path,
    evaluation_dir: Path,
    config: SplitConfig,
) -> PreparationResult:
    """Validate, group, split, and persist leakage-safe ULB partitions."""
    raw_copy_created = copy_immutable_source(source_path, raw_copy_path)
    frame, summary = validate_raw_dataset(
        raw_copy_path,
        expected_rows=config.expected_rows,
        expected_fraud_rows=config.expected_fraud_rows,
        expected_sha256=config.expected_sha256,
    )
    assignments = _partition_groups(frame, config)
    split_dir.mkdir(parents=True, exist_ok=True)
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    assignments_path = split_dir / "assignments.csv.gz"
    assignments.to_csv(assignments_path, index=False, compression="gzip")

    partition_rows: dict[str, int] = {}
    partition_fraud_rows: dict[str, int] = {}
    files: dict[str, str] = {"assignments": str(assignments_path)}
    for partition in ("train", "validation", "test"):
        row_indices = assignments.loc[
            assignments["partition"] == partition,
            "row_index",
        ]
        subset = frame.loc[row_indices].reset_index(drop=True)
        partition_rows[partition] = len(subset)
        partition_fraud_rows[partition] = int(subset["Class"].sum())
        if partition == "test":
            features_path = split_dir / "test_features.csv.gz"
            labels_path = evaluation_dir / "test_labels.csv.gz"
            subset.loc[:, RAW_FEATURES].to_csv(
                features_path,
                index=False,
                compression="gzip",
            )
            subset.loc[:, ["Class"]].to_csv(
                labels_path,
                index=False,
                compression="gzip",
            )
            files["test_features"] = str(features_path)
            files["test_labels"] = str(labels_path)
        else:
            path = split_dir / f"{partition}.csv.gz"
            subset.to_csv(path, index=False, compression="gzip")
            files[partition] = str(path)

    manifest = SplitManifest(
        version=config.version,
        seed=config.seed,
        raw_sha256=summary.sha256,
        assignment_sha256=_assignment_hash(assignments),
        source_rows=summary.rows,
        source_fraud_rows=summary.fraud_rows,
        feature_groups=int(assignments["group_id"].nunique()),
        duplicate_rows=summary.duplicate_rows,
        partition_rows=partition_rows,
        partition_fraud_rows=partition_fraud_rows,
        files=files,
    )
    manifest_path = split_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return PreparationResult(
        raw_summary=summary,
        manifest=manifest,
        raw_copy_created=raw_copy_created,
    )
