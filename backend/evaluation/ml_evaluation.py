"""Offline-only evaluation that opens test labels after model freeze."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backend.app.domain.base import ContractModel
from backend.app.ml.fraud_scorer import FraudScorer, FraudTransaction
from backend.app.ml.metrics import ModelMetrics, compute_metrics
from backend.app.ml.schema import RAW_FEATURES


class TestEvaluation(ContractModel):
    evaluation_version: str = "ulb_test_evaluation.v1"
    score_semantics: str = "ranking score; not a calibrated probability"
    models: dict[str, ModelMetrics]
    thresholds: dict[str, float]
    test_rows: int
    test_fraud_rows: int


def _score_frame(scorer: FraudScorer, frame: pd.DataFrame) -> np.ndarray:
    scores: list[float] = []
    batch_size = 5_000
    for start in range(0, len(frame), batch_size):
        batch = frame.iloc[start : start + batch_size]
        transactions = [
            FraudTransaction.model_validate(record) for record in batch.to_dict(orient="records")
        ]
        scores.extend(item.ml_score for item in scorer.score_batch(transactions))
    return np.asarray(scores, dtype=np.float64)


def evaluate_models(
    *,
    model_root: Path,
    split_dir: Path,
    evaluation_dir: Path,
    output_path: Path,
) -> TestEvaluation:
    """Evaluate frozen artifacts; this is the only module that opens test labels."""
    scorers = {
        model_name: FraudScorer.from_artifact(model_root / model_name)
        for model_name in ("logistic_regression", "random_forest")
    }
    features = pd.read_csv(split_dir / "test_features.csv.gz")
    if tuple(features.columns) != RAW_FEATURES:
        raise ValueError("test feature schema or field order does not match")

    labels_frame = pd.read_csv(evaluation_dir / "test_labels.csv.gz")
    if tuple(labels_frame.columns) != ("Class",):
        raise ValueError("test label file must contain only Class")
    labels = labels_frame["Class"].to_numpy(dtype=np.int64)
    if len(labels) != len(features):
        raise ValueError("test labels and features have different row counts")
    if set(np.unique(labels).tolist()) != {0, 1}:
        raise ValueError("test labels must contain both classes")

    metrics: dict[str, ModelMetrics] = {}
    thresholds: dict[str, float] = {}
    for model_name, scorer in scorers.items():
        scores = _score_frame(scorer, features)
        threshold = scorer.metadata.threshold_selection.threshold
        thresholds[model_name] = threshold
        metrics[model_name] = compute_metrics(labels, scores, threshold=threshold)
    result = TestEvaluation(
        models=metrics,
        thresholds=thresholds,
        test_rows=len(labels),
        test_fraud_rows=int(labels.sum()),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
