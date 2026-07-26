"""Deterministic Decimal-based descriptive robust statistics.

All arithmetic runs in a private 50-digit, half-even Decimal context so results
do not depend on the caller's active context. Quartiles use Hyndman-Fan type 7:
for sorted values and probability ``p``, position is ``(n - 1) * p`` and the
adjacent observations are linearly interpolated. IQR bounds are inclusive;
only values strictly outside them are marked as outliers.
"""

from decimal import MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from backend.app.domain.features import FeatureWarning
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

_CONTEXT = Context(
    prec=50,
    rounding=ROUND_HALF_EVEN,
    Emin=MIN_EMIN,
    Emax=MAX_EMAX,
)
_QUARTER = Decimal("0.25")
_THREE_QUARTERS = Decimal("0.75")


def _warning(code: str, message: str) -> FeatureWarning:
    return FeatureWarning(code=code, message=message)


def _availability_warnings(
    sample_size: int,
    minimum_sample_size: int,
    *,
    sample_name: str,
) -> tuple[FeatureWarning, ...]:
    if sample_size == 0:
        return (_warning("NO_DATA", f"The {sample_name} is empty; no statistic is available."),)
    if sample_size < minimum_sample_size:
        return (
            _warning(
                "INSUFFICIENT_DATA",
                f"The {sample_name} has {sample_size} observations; "
                f"at least {minimum_sample_size} are required.",
            ),
        )
    return ()


def _median(sorted_values: tuple[Decimal, ...]) -> Decimal:
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / Decimal(2)


def _mad(values: tuple[Decimal, ...]) -> tuple[Decimal, Decimal]:
    sorted_values = tuple(sorted(values))
    center = _median(sorted_values)
    deviations = tuple(sorted(abs(value - center) for value in sorted_values))
    return center, _median(deviations)


def _type_7_quantile(sorted_values: tuple[Decimal, ...], probability: Decimal) -> Decimal:
    position = Decimal(len(sorted_values) - 1) * probability
    lower_index = int(position)
    fraction = position - Decimal(lower_index)
    lower = sorted_values[lower_index]
    if fraction == 0:
        return lower
    upper = sorted_values[lower_index + 1]
    return lower + fraction * (upper - lower)


def median_absolute_deviation(
    request: MedianAbsoluteDeviationRequest,
) -> MedianAbsoluteDeviationResult:
    """Return the sample median and unscaled MAD when the sample is sufficient."""
    sample_size = len(request.values)
    warnings = _availability_warnings(
        sample_size,
        request.minimum_sample_size,
        sample_name="sample",
    )
    if warnings:
        return MedianAbsoluteDeviationResult(
            sample_size=sample_size,
            median=None,
            mad=None,
            warnings=warnings,
        )

    with localcontext(_CONTEXT):
        center, mad = _mad(request.values)
    dispersion_warnings = (
        (
            _warning(
                "ZERO_MAD",
                "The sample has zero median absolute deviation.",
            ),
        )
        if mad == 0
        else ()
    )
    return MedianAbsoluteDeviationResult(
        sample_size=sample_size,
        median=center,
        mad=mad,
        warnings=dispersion_warnings,
    )


def robust_z_score(request: RobustZScoreRequest) -> RobustZScoreResult:
    """Return ``factor * (value - median) / MAD`` as a descriptive signal."""
    sample_size = len(request.reference_values)
    warnings = _availability_warnings(
        sample_size,
        request.minimum_sample_size,
        sample_name="reference sample",
    )
    if warnings:
        return RobustZScoreResult(
            reference_sample_size=sample_size,
            reference_median=None,
            median_absolute_deviation=None,
            score=None,
            warnings=warnings,
        )

    with localcontext(_CONTEXT):
        center, mad = _mad(request.reference_values)
        score = request.consistency_factor * (request.value - center) / mad if mad != 0 else None
    dispersion_warnings = (
        (
            _warning(
                "ZERO_MAD",
                "The reference sample has zero MAD; a robust z-score is undefined.",
            ),
        )
        if mad == 0
        else ()
    )
    return RobustZScoreResult(
        reference_sample_size=sample_size,
        reference_median=center,
        median_absolute_deviation=mad,
        score=score,
        warnings=dispersion_warnings,
    )


def iqr_outliers(request: IqrOutlierRequest) -> IqrOutlierResult:
    """Return type-7 IQR bounds and an outlier mask preserving input order."""
    sample_size = len(request.values)
    warnings = _availability_warnings(
        sample_size,
        request.minimum_sample_size,
        sample_name="sample",
    )
    if warnings:
        return IqrOutlierResult(
            sample_size=sample_size,
            first_quartile=None,
            third_quartile=None,
            interquartile_range=None,
            lower_bound=None,
            upper_bound=None,
            outlier_mask=tuple(False for _ in request.values),
            warnings=warnings,
        )

    with localcontext(_CONTEXT):
        sorted_values = tuple(sorted(request.values))
        first_quartile = _type_7_quantile(sorted_values, _QUARTER)
        third_quartile = _type_7_quantile(sorted_values, _THREE_QUARTERS)
        iqr = third_quartile - first_quartile
        lower_bound = first_quartile - request.multiplier * iqr
        upper_bound = third_quartile + request.multiplier * iqr
        mask = tuple(value < lower_bound or value > upper_bound for value in request.values)
    dispersion_warnings = (
        (
            _warning(
                "ZERO_IQR",
                "The sample has zero IQR; bounds remain valid but dispersion is zero.",
            ),
        )
        if iqr == 0
        else ()
    )
    return IqrOutlierResult(
        sample_size=sample_size,
        first_quartile=first_quartile,
        third_quartile=third_quartile,
        interquartile_range=iqr,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        outlier_mask=mask,
        warnings=dispersion_warnings,
    )


def trailing_baseline_deviation(
    request: TrailingBaselineDeviationRequest,
) -> TrailingBaselineDeviationResult:
    """Compare a current value with the mean of explicit trailing period values."""
    sample_size = len(request.trailing_baseline_values)
    warnings = _availability_warnings(
        sample_size,
        request.minimum_baseline_size,
        sample_name="trailing baseline",
    )
    if warnings:
        return TrailingBaselineDeviationResult(
            baseline_sample_size=sample_size,
            baseline_mean=None,
            current_minus_baseline=None,
            absolute_deviation=None,
            relative_deviation=None,
            warnings=warnings,
        )

    with localcontext(_CONTEXT):
        baseline_mean = sum(request.trailing_baseline_values, Decimal(0)) / Decimal(sample_size)
        difference = request.current_value - baseline_mean
        absolute_deviation = abs(difference)
        relative_deviation = difference / baseline_mean if baseline_mean != 0 else None
    baseline_warnings = (
        (
            _warning(
                "ZERO_BASELINE",
                "The trailing baseline mean is zero; relative deviation is undefined.",
            ),
        )
        if baseline_mean == 0
        else ()
    )
    return TrailingBaselineDeviationResult(
        baseline_sample_size=sample_size,
        baseline_mean=baseline_mean,
        current_minus_baseline=difference,
        absolute_deviation=absolute_deviation,
        relative_deviation=relative_deviation,
        warnings=baseline_warnings,
    )
