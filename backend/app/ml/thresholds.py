"""Validation-only decision-threshold selection."""

import numpy as np
from pydantic import Field
from sklearn.metrics import precision_recall_curve

from backend.app.domain.base import ContractModel


class ThresholdSelection(ContractModel):
    threshold: float = Field(ge=0, le=1)
    precision: float = Field(ge=0, le=1)
    recall: float = Field(ge=0, le=1)
    f1: float = Field(ge=0, le=1)
    recall_floor: float = Field(ge=0, le=1)
    recall_floor_met: bool
    recipe: str = "validation_f1_with_recall_floor.v1"


def select_threshold(
    validation_labels: np.ndarray,
    validation_scores: np.ndarray,
    *,
    recall_floor: float,
) -> ThresholdSelection:
    """Maximize F1 subject to recall; break ties by recall then threshold."""
    if validation_labels.shape != validation_scores.shape:
        raise ValueError("validation labels and scores must have matching shapes")
    if validation_labels.ndim != 1 or validation_labels.size == 0:
        raise ValueError("validation labels and scores must be non-empty vectors")
    if not 0 <= recall_floor <= 1:
        raise ValueError("recall_floor must be between 0 and 1")
    precision, recall, thresholds = precision_recall_curve(
        validation_labels,
        validation_scores,
    )
    candidates: list[tuple[float, float, float, float]] = []
    fallback: list[tuple[float, float, float, float]] = []
    for threshold, candidate_precision, candidate_recall in zip(
        thresholds,
        precision[:-1],
        recall[:-1],
        strict=True,
    ):
        denominator = candidate_precision + candidate_recall
        f1 = 0.0 if denominator == 0 else 2 * candidate_precision * candidate_recall / denominator
        candidate = (
            float(f1),
            float(candidate_recall),
            float(threshold),
            float(candidate_precision),
        )
        fallback.append(candidate)
        if candidate_recall >= recall_floor:
            candidates.append(candidate)
    eligible = candidates or fallback
    if not eligible:
        raise ValueError("validation data produced no threshold candidates")
    best_f1, best_recall, best_threshold, best_precision = max(
        eligible,
        key=lambda item: (item[0], item[1], item[2]),
    )
    return ThresholdSelection(
        threshold=best_threshold,
        precision=best_precision,
        recall=best_recall,
        f1=best_f1,
        recall_floor=recall_floor,
        recall_floor_met=bool(candidates),
    )
