"""Public API for deterministic descriptive statistical helpers."""

from backend.app.tools.statistics.contracts import (
    IqrOutlierRequest,
    IqrOutlierResult,
    MedianAbsoluteDeviationRequest,
    MedianAbsoluteDeviationResult,
    RobustZScoreRequest,
    RobustZScoreResult,
    TrailingBaselineDeviationRequest,
    TrailingBaselineDeviationResult,
)
from backend.app.tools.statistics.robust import (
    iqr_outliers,
    median_absolute_deviation,
    robust_z_score,
    trailing_baseline_deviation,
)

__all__ = [
    "IqrOutlierRequest",
    "IqrOutlierResult",
    "MedianAbsoluteDeviationRequest",
    "MedianAbsoluteDeviationResult",
    "RobustZScoreRequest",
    "RobustZScoreResult",
    "TrailingBaselineDeviationRequest",
    "TrailingBaselineDeviationResult",
    "iqr_outliers",
    "median_absolute_deviation",
    "robust_z_score",
    "trailing_baseline_deviation",
]
