"""Fixture-first tests for immutable splitting, training, and scoring."""

from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.app.ml.fraud_scorer import FraudScorer, FraudTransaction
from backend.app.ml.prepare import (
    PreparationResult,
    SplitConfig,
    copy_immutable_source,
    prepare_ml_data,
)
from backend.app.ml.preprocessing import MODEL_FEATURE_ORDER, ULBPreprocessor
from backend.app.ml.schema import (
    RAW_COLUMNS,
    RAW_FEATURES,
    DatasetValidationError,
    sha256_file,
    validate_raw_dataset,
)
from backend.app.ml.thresholds import select_threshold
from backend.app.ml.training import TrainingConfig, train_models
from backend.evaluation.ml_evaluation import evaluate_models

FIXTURE = Path("backend/tests/fixtures/creditcard_tiny.csv")


def _split_config() -> SplitConfig:
    return SplitConfig(
        version="fixture_split.v1",
        seed=42,
        train_ratio=0.70,
        validation_ratio=0.15,
        test_ratio=0.15,
        expected_rows=22,
        expected_fraud_rows=11,
        expected_sha256=sha256_file(FIXTURE),
        grouping="exact_match_all_30_non_label_columns",
    )


def _training_config() -> TrainingConfig:
    return TrainingConfig.model_validate(
        {
            "version": "fixture_training.v1",
            "preprocessing_version": "preprocessing.v1",
            "seed": 42,
            "threshold": {
                "metric": "f1",
                "recall_floor": 0.8,
                "tie_breaking": ["highest_f1", "highest_recall", "highest_threshold"],
            },
            "logistic_regression": {
                "class_weight": "balanced",
                "max_iter": 200,
                "solver": "lbfgs",
            },
            "random_forest": {
                "class_weight": "balanced_subsample",
                "n_estimators": 10,
                "max_depth": 4,
                "min_samples_leaf": 1,
                "n_jobs": 1,
            },
        }
    )


def _prepare(tmp_path: Path) -> PreparationResult:
    return prepare_ml_data(
        source_path=FIXTURE,
        raw_copy_path=tmp_path / "raw" / "creditcard.csv",
        split_dir=tmp_path / "splits",
        evaluation_dir=tmp_path / "evaluation",
        config=_split_config(),
    )


def test_raw_validation_and_schema_failures(tmp_path: Path) -> None:
    frame, summary = validate_raw_dataset(
        FIXTURE,
        expected_rows=22,
        expected_fraud_rows=11,
        expected_sha256=sha256_file(FIXTURE),
    )
    assert tuple(frame.columns) == RAW_COLUMNS
    assert summary.duplicate_rows == 2
    assert summary.clean_rows == summary.fraud_rows == 11

    with pytest.raises(DatasetValidationError, match="SHA256"):
        validate_raw_dataset(FIXTURE, expected_sha256="0" * 64)
    with pytest.raises(DatasetValidationError, match="row count"):
        validate_raw_dataset(FIXTURE, expected_rows=1)
    with pytest.raises(DatasetValidationError, match="fraud count"):
        validate_raw_dataset(FIXTURE, expected_fraud_rows=1)

    missing_column = frame.drop(columns=["V28"])
    missing_path = tmp_path / "missing.csv"
    missing_column.to_csv(missing_path, index=False)
    with pytest.raises(DatasetValidationError, match="expected columns"):
        validate_raw_dataset(missing_path)

    null_frame = frame.copy()
    null_frame.loc[0, "V1"] = np.nan
    null_path = tmp_path / "null.csv"
    null_frame.to_csv(null_path, index=False)
    with pytest.raises(DatasetValidationError, match="null"):
        validate_raw_dataset(null_path)

    negative = frame.copy()
    negative.loc[0, "Amount"] = -1
    negative_path = tmp_path / "negative.csv"
    negative.to_csv(negative_path, index=False)
    with pytest.raises(DatasetValidationError, match="negative"):
        validate_raw_dataset(negative_path)


def test_duplicate_group_split_is_deterministic_and_immutable(tmp_path: Path) -> None:
    first = _prepare(tmp_path)
    second = _prepare(tmp_path)
    assert first.raw_copy_created is True
    assert second.raw_copy_created is False
    assert first.manifest.assignment_sha256 == second.manifest.assignment_sha256
    assert first.manifest.duplicate_rows == 2
    assignments = pd.read_csv(tmp_path / "splits" / "assignments.csv.gz")
    assert assignments.groupby("group_id")["partition"].nunique().max() == 1
    assert set(assignments["partition"]) == {"train", "validation", "test"}

    changed_source = tmp_path / "changed.csv"
    changed_source.write_text(FIXTURE.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="immutable"):
        copy_immutable_source(changed_source, tmp_path / "raw" / "creditcard.csv")

    conflicting = pd.read_csv(FIXTURE)
    conflicting.loc[2, "Class"] = 1
    conflict_path = tmp_path / "conflicting.csv"
    conflicting.to_csv(conflict_path, index=False)
    config = _split_config().model_copy(
        update={
            "expected_sha256": None,
            "expected_fraud_rows": None,
        }
    )
    with pytest.raises(DatasetValidationError, match="conflicting"):
        prepare_ml_data(
            source_path=conflict_path,
            raw_copy_path=tmp_path / "other-raw.csv",
            split_dir=tmp_path / "other-splits",
            evaluation_dir=tmp_path / "other-evaluation",
            config=config,
        )


def test_preprocessing_threshold_training_evaluation_and_scorer(tmp_path: Path) -> None:
    _prepare(tmp_path)
    train_frame = pd.read_csv(tmp_path / "splits" / "train.csv.gz")
    features = train_frame.loc[:, RAW_FEATURES]
    preprocessor = ULBPreprocessor().fit(features)
    transformed = preprocessor.transform(features)
    assert transformed.shape == (len(features), len(MODEL_FEATURE_ORDER))
    assert tuple(preprocessor.get_feature_names_out()) == MODEL_FEATURE_ORDER
    assert preprocessor.scaler.mean_ is not None
    assert preprocessor.scaler.mean_[-1] == pytest.approx(np.log1p(features["Amount"]).mean())
    changed_time = features.copy()
    changed_time["Time"] += 1_000_000
    np.testing.assert_allclose(transformed, preprocessor.transform(changed_time))

    threshold = select_threshold(
        np.asarray([0, 0, 1, 1], dtype=np.int64),
        np.asarray([0.1, 0.3, 0.7, 0.9], dtype=np.float64),
        recall_floor=0.8,
    )
    assert threshold.recall_floor_met is True
    assert threshold.threshold >= 0.7

    model_root = tmp_path / "models"
    training = train_models(
        split_dir=tmp_path / "splits",
        model_root=model_root,
        config=_training_config(),
    )
    assert {model.model_name for model in training.models} == {
        "logistic_regression",
        "random_forest",
    }
    evaluation = evaluate_models(
        model_root=model_root,
        split_dir=tmp_path / "splits",
        evaluation_dir=tmp_path / "evaluation",
        output_path=tmp_path / "metrics.json",
    )
    assert evaluation.test_rows > 0
    assert set(evaluation.models) == {"logistic_regression", "random_forest"}

    sample = pd.read_csv(tmp_path / "splits" / "test_features.csv.gz", nrows=1)
    ordered = OrderedDict((column, float(sample.iloc[0][column])) for column in RAW_FEATURES)
    transaction = FraudScorer.validate_ordered_mapping(ordered)
    scorer = FraudScorer.from_artifact(model_root / "selected")
    first = scorer.score_one(transaction)
    second = scorer.score_one(transaction)
    batch = scorer.score_batch([transaction])[0]
    assert first == second == batch
    assert scorer.score_batch([]) == []

    reversed_mapping = OrderedDict(reversed(tuple(ordered.items())))
    with pytest.raises(ValueError, match="ordered fields"):
        FraudScorer.validate_ordered_mapping(reversed_mapping)
    with pytest.raises(ValueError):
        FraudTransaction.model_validate({**ordered, "unexpected": 1})

    training_source = Path("backend/app/ml/training.py").read_text(encoding="utf-8")
    assert "test_labels" not in training_source
    assert "backend.evaluation" not in training_source
