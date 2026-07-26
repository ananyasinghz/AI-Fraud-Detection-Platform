"""Hand-calculated tests for deterministic descriptive statistics."""

from decimal import Decimal, getcontext

import pytest
from pydantic import ValidationError

from backend.app.domain.features import FeatureWarning
from backend.app.tools.statistics import (
    IqrOutlierRequest,
    MedianAbsoluteDeviationRequest,
    MedianAbsoluteDeviationResult,
    RobustZScoreRequest,
    TrailingBaselineDeviationRequest,
    iqr_outliers,
    median_absolute_deviation,
    robust_z_score,
    trailing_baseline_deviation,
)


def decimals(*values: str) -> tuple[Decimal, ...]:
    return tuple(Decimal(value) for value in values)


def warning_codes(warnings: tuple[FeatureWarning, ...]) -> tuple[str, ...]:
    return tuple(item.code for item in warnings)


def test_mad_uses_exact_median_for_odd_and_even_samples() -> None:
    odd = median_absolute_deviation(
        MedianAbsoluteDeviationRequest(values=decimals("1", "2", "3", "4", "100"))
    )
    even = median_absolute_deviation(
        MedianAbsoluteDeviationRequest(values=decimals("1", "2", "4", "8"))
    )

    assert (odd.median, odd.mad) == (Decimal(3), Decimal(1))
    assert (even.median, even.mad) == (Decimal(3), Decimal("1.5"))


def test_mad_reports_empty_insufficient_and_zero_dispersion() -> None:
    empty = median_absolute_deviation(MedianAbsoluteDeviationRequest(values=()))
    insufficient = median_absolute_deviation(
        MedianAbsoluteDeviationRequest(
            values=decimals("1", "2"),
            minimum_sample_size=3,
        )
    )
    zero = median_absolute_deviation(MedianAbsoluteDeviationRequest(values=decimals("7", "7", "7")))

    assert (empty.median, empty.mad, warning_codes(empty.warnings)) == (
        None,
        None,
        ("NO_DATA",),
    )
    assert (insufficient.median, insufficient.mad) == (None, None)
    assert warning_codes(insufficient.warnings) == ("INSUFFICIENT_DATA",)
    assert (zero.median, zero.mad, warning_codes(zero.warnings)) == (
        Decimal(7),
        Decimal(0),
        ("ZERO_MAD",),
    )


def test_robust_z_score_is_hand_calculated_and_not_a_label() -> None:
    result = robust_z_score(
        RobustZScoreRequest(
            value=Decimal(5),
            reference_values=decimals("1", "2", "3", "4", "100"),
        )
    )

    assert result.reference_median == Decimal(3)
    assert result.median_absolute_deviation == Decimal(1)
    assert result.score == Decimal("1.3490")
    assert not hasattr(result, "risk")
    assert result.warnings == ()


def test_robust_z_score_handles_insufficient_and_zero_mad() -> None:
    insufficient = robust_z_score(
        RobustZScoreRequest(
            value=Decimal(2),
            reference_values=decimals("1", "2"),
        )
    )
    zero = robust_z_score(
        RobustZScoreRequest(
            value=Decimal(9),
            reference_values=decimals("4", "4", "4"),
        )
    )

    assert insufficient.score is None
    assert warning_codes(insufficient.warnings) == ("INSUFFICIENT_DATA",)
    assert (zero.reference_median, zero.median_absolute_deviation, zero.score) == (
        Decimal(4),
        Decimal(0),
        None,
    )
    assert warning_codes(zero.warnings) == ("ZERO_MAD",)


def test_iqr_uses_documented_type_7_interpolation_and_marks_outliers() -> None:
    result = iqr_outliers(IqrOutlierRequest(values=decimals("1", "2", "3", "4", "100")))

    assert result.first_quartile == Decimal(2)
    assert result.third_quartile == Decimal(4)
    assert result.interquartile_range == Decimal(2)
    assert result.lower_bound == Decimal("-1.0")
    assert result.upper_bound == Decimal("7.0")
    assert result.outlier_mask == (False, False, False, False, True)


def test_iqr_type_7_linearly_interpolates_fractional_positions() -> None:
    result = iqr_outliers(IqrOutlierRequest(values=decimals("0", "10", "20", "30", "40", "50")))

    assert result.first_quartile == Decimal("12.50")
    assert result.third_quartile == Decimal("37.50")
    assert result.interquartile_range == Decimal("25.00")


def test_iqr_bounds_are_inclusive_and_preserve_input_order() -> None:
    result = iqr_outliers(
        IqrOutlierRequest(
            values=decimals("4", "0", "3", "1", "2"),
            multiplier=Decimal(0),
        )
    )

    assert (result.first_quartile, result.third_quartile) == (Decimal(1), Decimal(3))
    assert (result.lower_bound, result.upper_bound) == (Decimal(1), Decimal(3))
    assert result.outlier_mask == (True, True, False, False, False)


def test_iqr_handles_empty_insufficient_and_zero_dispersion() -> None:
    empty = iqr_outliers(IqrOutlierRequest(values=()))
    insufficient = iqr_outliers(IqrOutlierRequest(values=decimals("1", "2", "3")))
    zero = iqr_outliers(IqrOutlierRequest(values=decimals("2", "2", "2", "2")))

    assert empty.first_quartile is None
    assert empty.outlier_mask == ()
    assert warning_codes(empty.warnings) == ("NO_DATA",)
    assert insufficient.outlier_mask == (False, False, False)
    assert warning_codes(insufficient.warnings) == ("INSUFFICIENT_DATA",)
    assert (
        zero.first_quartile,
        zero.third_quartile,
        zero.interquartile_range,
        zero.lower_bound,
        zero.upper_bound,
    ) == (Decimal(2), Decimal(2), Decimal(0), Decimal(2), Decimal(2))
    assert zero.outlier_mask == (False, False, False, False)
    assert warning_codes(zero.warnings) == ("ZERO_IQR",)


def test_trailing_baseline_deviation_uses_explicit_baseline_mean() -> None:
    above = trailing_baseline_deviation(
        TrailingBaselineDeviationRequest(
            current_value=Decimal(15),
            trailing_baseline_values=decimals("8", "10", "12"),
        )
    )
    below = trailing_baseline_deviation(
        TrailingBaselineDeviationRequest(
            current_value=Decimal(5),
            trailing_baseline_values=decimals("8", "10", "12"),
        )
    )

    assert (
        above.baseline_mean,
        above.current_minus_baseline,
        above.absolute_deviation,
        above.relative_deviation,
    ) == (Decimal(10), Decimal(5), Decimal(5), Decimal("0.5"))
    assert (
        below.current_minus_baseline,
        below.absolute_deviation,
        below.relative_deviation,
    ) == (Decimal(-5), Decimal(5), Decimal("-0.5"))


def test_trailing_baseline_handles_empty_insufficient_and_zero_mean() -> None:
    empty = trailing_baseline_deviation(
        TrailingBaselineDeviationRequest(
            current_value=Decimal(1),
            trailing_baseline_values=(),
        )
    )
    insufficient = trailing_baseline_deviation(
        TrailingBaselineDeviationRequest(
            current_value=Decimal(1),
            trailing_baseline_values=decimals("1", "2"),
            minimum_baseline_size=3,
        )
    )
    zero = trailing_baseline_deviation(
        TrailingBaselineDeviationRequest(
            current_value=Decimal(3),
            trailing_baseline_values=decimals("-1", "1"),
        )
    )

    assert empty.baseline_mean is None
    assert warning_codes(empty.warnings) == ("NO_DATA",)
    assert insufficient.baseline_mean is None
    assert warning_codes(insufficient.warnings) == ("INSUFFICIENT_DATA",)
    assert (
        zero.baseline_mean,
        zero.current_minus_baseline,
        zero.absolute_deviation,
        zero.relative_deviation,
    ) == (Decimal(0), Decimal(3), Decimal(3), None)
    assert warning_codes(zero.warnings) == ("ZERO_BASELINE",)


@pytest.mark.parametrize("non_finite", [Decimal("NaN"), Decimal("Infinity")])
def test_contracts_reject_non_finite_values(non_finite: Decimal) -> None:
    with pytest.raises(ValidationError, match="finite"):
        MedianAbsoluteDeviationRequest(values=(non_finite,))
    with pytest.raises(ValidationError, match="finite"):
        RobustZScoreRequest(value=non_finite, reference_values=decimals("1", "2", "3"))
    with pytest.raises(ValidationError, match="finite"):
        IqrOutlierRequest(values=decimals("1", "2", "3", "4"), multiplier=non_finite)
    with pytest.raises(ValidationError, match="finite"):
        TrailingBaselineDeviationRequest(
            current_value=Decimal(1),
            trailing_baseline_values=(non_finite,),
        )
    with pytest.raises(ValidationError, match="finite"):
        MedianAbsoluteDeviationResult(
            sample_size=1,
            median=non_finite,
            mad=Decimal(0),
        )


def test_contracts_are_strict_and_immutable() -> None:
    request = MedianAbsoluteDeviationRequest(values=decimals("1", "2"))
    result = median_absolute_deviation(request)

    with pytest.raises(ValidationError):
        MedianAbsoluteDeviationRequest(values=[Decimal(1)])  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="frozen"):
        request.minimum_sample_size = 2
    with pytest.raises(ValidationError, match="frozen"):
        result.median = Decimal(0)


def test_repeated_calls_ignore_the_ambient_decimal_context() -> None:
    request = RobustZScoreRequest(
        value=Decimal("9.87654321"),
        reference_values=decimals("1.1", "2.2", "4.4", "8.8", "17.6"),
    )
    original_precision = getcontext().prec
    try:
        getcontext().prec = 3
        first = robust_z_score(request)
        getcontext().prec = 28
        second = robust_z_score(request)
    finally:
        getcontext().prec = original_precision

    assert first == second
