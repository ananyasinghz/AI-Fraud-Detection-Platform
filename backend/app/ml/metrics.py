"""Shared metric computation for validation and offline test evaluation."""

import numpy as np
from pydantic import Field
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from backend.app.domain.base import ContractModel


class ModelMetrics(ContractModel):
    pr_auc: float = Field(ge=0, le=1)
    roc_auc: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    true_negative: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_positive: int = Field(ge=0)
    alert_rate: float = Field(ge=0, le=1)
    brier_diagnostic: float = Field(ge=0)


def compute_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    *,
    threshold: float,
) -> ModelMetrics:
    if labels.shape != scores.shape or labels.ndim != 1:
        raise ValueError("labels and scores must be matching one-dimensional arrays")
    predictions = (scores >= threshold).astype(np.int64)
    true_negative, false_positive, false_negative, true_positive = confusion_matrix(
        labels,
        predictions,
        labels=[0, 1],
    ).ravel()
    return ModelMetrics(
        pr_auc=float(average_precision_score(labels, scores)),
        roc_auc=float(roc_auc_score(labels, scores)),
        precision=float(precision_score(labels, predictions, zero_division=0)),
        recall=float(recall_score(labels, predictions, zero_division=0)),
        f1=float(f1_score(labels, predictions, zero_division=0)),
        true_negative=int(true_negative),
        false_positive=int(false_positive),
        false_negative=int(false_negative),
        true_positive=int(true_positive),
        alert_rate=float(predictions.mean()),
        brier_diagnostic=float(brier_score_loss(labels, scores)),
    )
