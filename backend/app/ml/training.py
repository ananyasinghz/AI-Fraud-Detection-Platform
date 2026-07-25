"""First-party logistic-regression and Random Forest training."""

import json
import platform
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
import sklearn
import yaml
from pydantic import Field
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from backend.app.domain.base import ContractModel
from backend.app.ml.metrics import ModelMetrics, compute_metrics
from backend.app.ml.prepare import SplitManifest
from backend.app.ml.preprocessing import (
    MODEL_FEATURE_ORDER,
    PREPROCESSING_VERSION,
    ULBPreprocessor,
)
from backend.app.ml.schema import RAW_COLUMNS, RAW_FEATURES, read_raw_dataset
from backend.app.ml.thresholds import ThresholdSelection, select_threshold


class ThresholdConfig(ContractModel):
    metric: Literal["f1"]
    recall_floor: float = Field(ge=0, le=1)
    tie_breaking: list[str]


class LogisticConfig(ContractModel):
    class_weight: Literal["balanced"]
    max_iter: int = Field(ge=1)
    solver: Literal[
        "lbfgs",
        "liblinear",
        "newton-cg",
        "newton-cholesky",
        "sag",
        "saga",
    ]


class RandomForestConfig(ContractModel):
    class_weight: Literal["balanced", "balanced_subsample"]
    n_estimators: int = Field(ge=1)
    max_depth: int | None = Field(default=None, ge=1)
    min_samples_leaf: int = Field(ge=1)
    n_jobs: int


class TrainingConfig(ContractModel):
    version: str
    preprocessing_version: Literal["preprocessing.v1"]
    seed: int = Field(ge=0)
    threshold: ThresholdConfig
    logistic_regression: LogisticConfig
    random_forest: RandomForestConfig


class ArtifactMetadata(ContractModel):
    artifact_schema_version: str = "fraud_scorer_artifact.v1"
    model_version: str
    model_type: Literal["logistic_regression", "random_forest"]
    preprocessing_version: str
    raw_input_order: list[str]
    output_feature_order: list[str]
    threshold_selection: ThresholdSelection
    raw_sha256: str
    split_version: str
    split_assignment_sha256: str
    seed: int
    training_rows: int
    training_fraud_rows: int
    validation_rows: int
    validation_fraud_rows: int
    validation_metrics: ModelMetrics
    library_versions: dict[str, str]
    score_semantics: str = "ranking score; not a calibrated probability"


class ModelTrainingResult(ContractModel):
    model_name: str
    artifact_dir: str
    metadata: ArtifactMetadata


class TrainingResult(ContractModel):
    selected_model: str
    selected_artifact_dir: str
    models: list[ModelTrainingResult]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return value


def load_training_config(path: Path) -> TrainingConfig:
    return TrainingConfig.model_validate(_read_yaml(path))


def _load_split_manifest(path: Path) -> SplitManifest:
    return SplitManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _load_labeled_partition(path: Path) -> pd.DataFrame:
    frame = read_raw_dataset(path)
    if tuple(frame.columns) != RAW_COLUMNS:
        raise ValueError("labeled partition schema drifted")
    return frame


def _library_versions() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "joblib": joblib.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _build_models(config: TrainingConfig) -> dict[str, object]:
    logistic = config.logistic_regression
    forest = config.random_forest
    return {
        "logistic_regression": LogisticRegression(
            class_weight=logistic.class_weight,
            max_iter=logistic.max_iter,
            solver=logistic.solver,
            random_state=config.seed,
        ),
        "random_forest": RandomForestClassifier(
            class_weight=forest.class_weight,
            n_estimators=forest.n_estimators,
            max_depth=forest.max_depth,
            min_samples_leaf=forest.min_samples_leaf,
            n_jobs=forest.n_jobs,
            random_state=config.seed,
        ),
    }


def _write_artifact(
    pipeline: Pipeline,
    metadata: ArtifactMetadata,
    artifact_dir: Path,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, artifact_dir / "model.joblib")
    (artifact_dir / "metadata.json").write_text(
        json.dumps(metadata.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def train_models(
    *,
    split_dir: Path,
    model_root: Path,
    config: TrainingConfig,
) -> TrainingResult:
    """Train only on train data and freeze thresholds using validation data."""
    split_manifest = _load_split_manifest(split_dir / "manifest.json")
    train_frame = _load_labeled_partition(split_dir / "train.csv.gz")
    validation_frame = _load_labeled_partition(split_dir / "validation.csv.gz")
    train_features = train_frame.loc[:, RAW_FEATURES]
    train_labels = train_frame["Class"].to_numpy(dtype=np.int64)
    validation_features = validation_frame.loc[:, RAW_FEATURES]
    validation_labels = validation_frame["Class"].to_numpy(dtype=np.int64)

    trained: list[tuple[str, Pipeline, ArtifactMetadata]] = []
    for model_name, classifier in _build_models(config).items():
        pipeline = Pipeline(
            steps=[
                ("preprocessor", ULBPreprocessor()),
                ("classifier", classifier),
            ]
        )
        pipeline.fit(train_features, train_labels)
        validation_scores = np.asarray(
            pipeline.predict_proba(validation_features)[:, 1],
            dtype=np.float64,
        )
        threshold = select_threshold(
            validation_labels,
            validation_scores,
            recall_floor=config.threshold.recall_floor,
        )
        metrics = compute_metrics(
            validation_labels,
            validation_scores,
            threshold=threshold.threshold,
        )
        typed_model_name: Literal["logistic_regression", "random_forest"] = (
            "logistic_regression" if model_name == "logistic_regression" else "random_forest"
        )
        metadata = ArtifactMetadata(
            model_version=f"ulb.{model_name}.v1",
            model_type=typed_model_name,
            preprocessing_version=PREPROCESSING_VERSION,
            raw_input_order=list(RAW_FEATURES),
            output_feature_order=list(MODEL_FEATURE_ORDER),
            threshold_selection=threshold,
            raw_sha256=split_manifest.raw_sha256,
            split_version=split_manifest.version,
            split_assignment_sha256=split_manifest.assignment_sha256,
            seed=config.seed,
            training_rows=len(train_frame),
            training_fraud_rows=int(train_labels.sum()),
            validation_rows=len(validation_frame),
            validation_fraud_rows=int(validation_labels.sum()),
            validation_metrics=metrics,
            library_versions=_library_versions(),
        )
        artifact_dir = model_root / model_name
        _write_artifact(pipeline, metadata, artifact_dir)
        trained.append((model_name, pipeline, metadata))

    selected_name, selected_pipeline, selected_metadata = max(
        trained,
        key=lambda item: (
            item[2].validation_metrics.pr_auc,
            item[2].validation_metrics.f1,
            item[0],
        ),
    )
    selected_dir = model_root / "selected"
    _write_artifact(selected_pipeline, selected_metadata, selected_dir)
    selection = {
        "selection_basis": ["validation_pr_auc", "validation_f1", "model_name"],
        "selected_model": selected_name,
        "selected_model_version": selected_metadata.model_version,
    }
    (model_root / "selection.json").write_text(
        json.dumps(selection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return TrainingResult(
        selected_model=selected_name,
        selected_artifact_dir=str(selected_dir),
        models=[
            ModelTrainingResult(
                model_name=name,
                artifact_dir=str(model_root / name),
                metadata=metadata,
            )
            for name, _, metadata in trained
        ],
    )
