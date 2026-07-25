"""Strict ULB dataset schema and immutable-file validation."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import Field

from backend.app.domain.base import ContractModel

PCA_FEATURES = tuple(f"V{index}" for index in range(1, 29))
RAW_FEATURES = ("Time", *PCA_FEATURES, "Amount")
RAW_COLUMNS = (*RAW_FEATURES, "Class")


class DatasetValidationError(ValueError):
    """Raised when source data violates the pinned ULB contract."""


class RawDatasetSummary(ContractModel):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    rows: int = Field(ge=1)
    fraud_rows: int = Field(ge=1)
    clean_rows: int = Field(ge=1)
    duplicate_rows: int = Field(ge=0)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_raw_dataset(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if tuple(frame.columns) != RAW_COLUMNS:
        raise DatasetValidationError(
            f"expected columns {RAW_COLUMNS}, received {tuple(frame.columns)}"
        )
    if frame.isna().any().any():
        null_columns = frame.columns[frame.isna().any()].tolist()
        raise DatasetValidationError(f"null values found in columns: {null_columns}")
    values = frame.loc[:, RAW_FEATURES].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise DatasetValidationError("all ULB feature values must be finite numbers")
    if (frame["Amount"] < 0).any():
        raise DatasetValidationError("Amount cannot be negative")
    labels = set(frame["Class"].unique().tolist())
    if labels != {0, 1}:
        raise DatasetValidationError(f"Class must contain exactly 0 and 1; received {labels}")
    return frame


def validate_raw_dataset(
    path: Path,
    *,
    expected_rows: int | None = None,
    expected_fraud_rows: int | None = None,
    expected_sha256: str | None = None,
) -> tuple[pd.DataFrame, RawDatasetSummary]:
    if not path.is_file():
        raise FileNotFoundError(path)
    fingerprint = sha256_file(path)
    if expected_sha256 is not None and fingerprint != expected_sha256:
        raise DatasetValidationError(
            f"SHA256 mismatch for {path}: expected {expected_sha256}, got {fingerprint}"
        )
    frame = read_raw_dataset(path)
    fraud_rows = int(frame["Class"].sum())
    if expected_rows is not None and len(frame) != expected_rows:
        raise DatasetValidationError(
            f"row count mismatch: expected {expected_rows}, got {len(frame)}"
        )
    if expected_fraud_rows is not None and fraud_rows != expected_fraud_rows:
        raise DatasetValidationError(
            f"fraud count mismatch: expected {expected_fraud_rows}, got {fraud_rows}"
        )
    summary = RawDatasetSummary(
        path=str(path),
        sha256=fingerprint,
        rows=len(frame),
        fraud_rows=fraud_rows,
        clean_rows=len(frame) - fraud_rows,
        duplicate_rows=int(frame.duplicated(subset=list(RAW_FEATURES)).sum()),
    )
    return frame, summary
