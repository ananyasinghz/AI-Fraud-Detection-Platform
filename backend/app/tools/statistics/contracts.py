"""Strict immutable contracts for descriptive robust statistics."""

from decimal import Decimal

from pydantic import Field, field_validator

from backend.app.domain.features import FeatureWarning, FrozenContractModel


def _finite(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite():
        raise ValueError(f"{field_name} must contain only finite Decimal values")
    return value


def _finite_tuple(values: tuple[Decimal, ...], field_name: str) -> tuple[Decimal, ...]:
    for value in values:
        _finite(value, field_name)
    return values


def _finite_optional(value: Decimal | None, field_name: str) -> Decimal | None:
    return _finite(value, field_name) if value is not None else None


class MedianAbsoluteDeviationRequest(FrozenContractModel):
    """Input sample and explicit sufficiency requirement for MAD."""

    values: tuple[Decimal, ...]
    minimum_sample_size: int = Field(default=1, ge=1)

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        return _finite_tuple(values, "values")


class MedianAbsoluteDeviationResult(FrozenContractModel):
    """Median and unscaled median absolute deviation of a sample."""

    sample_size: int = Field(ge=0)
    median: Decimal | None
    mad: Decimal | None = Field(ge=0)
    warnings: tuple[FeatureWarning, ...] = ()

    @field_validator("median", "mad")
    @classmethod
    def validate_statistics(cls, value: Decimal | None) -> Decimal | None:
        return _finite_optional(value, "statistics")


class RobustZScoreRequest(FrozenContractModel):
    """Value compared with an explicit reference sample using median and MAD."""

    value: Decimal
    reference_values: tuple[Decimal, ...]
    minimum_sample_size: int = Field(default=3, ge=1)
    consistency_factor: Decimal = Field(default=Decimal("0.6745"), gt=0)

    @field_validator("value", "consistency_factor")
    @classmethod
    def validate_scalar(cls, value: Decimal) -> Decimal:
        return _finite(value, "numeric inputs")

    @field_validator("reference_values")
    @classmethod
    def validate_reference_values(
        cls,
        values: tuple[Decimal, ...],
    ) -> tuple[Decimal, ...]:
        return _finite_tuple(values, "reference_values")


class RobustZScoreResult(FrozenContractModel):
    """Descriptive robust standardized deviation; it is not a risk label."""

    reference_sample_size: int = Field(ge=0)
    reference_median: Decimal | None
    median_absolute_deviation: Decimal | None = Field(ge=0)
    score: Decimal | None
    warnings: tuple[FeatureWarning, ...] = ()

    @field_validator("reference_median", "median_absolute_deviation", "score")
    @classmethod
    def validate_statistics(cls, value: Decimal | None) -> Decimal | None:
        return _finite_optional(value, "statistics")


class IqrOutlierRequest(FrozenContractModel):
    """Sample and explicit parameters for IQR bounds and outlier descriptions."""

    values: tuple[Decimal, ...]
    minimum_sample_size: int = Field(default=4, ge=1)
    multiplier: Decimal = Field(default=Decimal("1.5"), ge=0)

    @field_validator("multiplier")
    @classmethod
    def validate_multiplier(cls, value: Decimal) -> Decimal:
        return _finite(value, "multiplier")

    @field_validator("values")
    @classmethod
    def validate_values(cls, values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        return _finite_tuple(values, "values")


class IqrOutlierResult(FrozenContractModel):
    """Type-7 quartiles, inclusive bounds, and input-order outlier mask."""

    sample_size: int = Field(ge=0)
    first_quartile: Decimal | None
    third_quartile: Decimal | None
    interquartile_range: Decimal | None = Field(ge=0)
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    outlier_mask: tuple[bool, ...]
    warnings: tuple[FeatureWarning, ...] = ()

    @field_validator(
        "first_quartile",
        "third_quartile",
        "interquartile_range",
        "lower_bound",
        "upper_bound",
    )
    @classmethod
    def validate_statistics(cls, value: Decimal | None) -> Decimal | None:
        return _finite_optional(value, "statistics")


class TrailingBaselineDeviationRequest(FrozenContractModel):
    """Current-period value compared with explicit trailing period values."""

    current_value: Decimal
    trailing_baseline_values: tuple[Decimal, ...]
    minimum_baseline_size: int = Field(default=1, ge=1)

    @field_validator("current_value")
    @classmethod
    def validate_current_value(cls, value: Decimal) -> Decimal:
        return _finite(value, "current_value")

    @field_validator("trailing_baseline_values")
    @classmethod
    def validate_baseline_values(
        cls,
        values: tuple[Decimal, ...],
    ) -> tuple[Decimal, ...]:
        return _finite_tuple(values, "trailing_baseline_values")


class TrailingBaselineDeviationResult(FrozenContractModel):
    """Descriptive deviation from the arithmetic mean trailing baseline."""

    baseline_sample_size: int = Field(ge=0)
    baseline_mean: Decimal | None
    current_minus_baseline: Decimal | None
    absolute_deviation: Decimal | None
    relative_deviation: Decimal | None
    warnings: tuple[FeatureWarning, ...] = ()

    @field_validator(
        "baseline_mean",
        "current_minus_baseline",
        "absolute_deviation",
        "relative_deviation",
    )
    @classmethod
    def validate_statistics(cls, value: Decimal | None) -> Decimal | None:
        return _finite_optional(value, "statistics")
