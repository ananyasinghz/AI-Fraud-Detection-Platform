"""Strict contracts for versioned, query-scoped feature operations."""

from datetime import datetime, timedelta
from decimal import Decimal
from math import isfinite
from typing import Annotated

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.enums import (
    EntityType,
    FeatureGrouping,
    TransactionDirection,
    ValueType,
)

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"),
]
OperationName = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$"),
]
Version = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"),
]
ScalarValue = int | Decimal | float | bool | str


class FrozenContractModel(ContractModel):
    """Strict, frozen base for detection contracts."""

    model_config = ConfigDict(strict=True, frozen=True)


def _require_utc(value: datetime, field_name: str) -> datetime:
    if not is_timezone_aware(value) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC-aware")
    return value


class FeatureWindow(FrozenContractModel):
    """A half-open event-time interval: start_inclusive <= t < end_exclusive."""

    start_inclusive: datetime
    end_exclusive: datetime

    @field_validator("start_inclusive", "end_exclusive")
    @classmethod
    def validate_utc_bound(cls, value: datetime, info: ValidationInfo) -> datetime:
        return _require_utc(value, info.field_name or "window boundary")

    @model_validator(mode="after")
    def validate_order(self) -> "FeatureWindow":
        if self.start_inclusive >= self.end_exclusive:
            raise ValueError("half-open window must have start_inclusive < end_exclusive")
        return self


class EntityScope(FrozenContractModel):
    """The entities whose activity may contribute to a feature."""

    entity_type: EntityType
    entity_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=100)

    @field_validator("entity_ids")
    @classmethod
    def validate_unique_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("entity_ids cannot contain duplicates")
        return values


class TransactionFilter(FrozenContractModel):
    """Transaction predicates applied without widening the entity scope."""

    transaction_types: tuple[str, ...] = Field(default=(), max_length=50)
    directions: tuple[TransactionDirection, ...] = Field(default=(), max_length=2)
    channels: tuple[str, ...] = Field(default=(), max_length=50)
    countries: tuple[str, ...] = Field(default=(), max_length=50)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    minimum_amount_minor: int | None = Field(default=None, ge=0)
    maximum_amount_minor: int | None = Field(default=None, ge=0)

    @field_validator("transaction_types", "channels")
    @classmethod
    def validate_names(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value or len(value) > 64 for value in values):
            raise ValueError("filter names must contain 1 to 64 characters")
        if len(values) != len(set(values)):
            raise ValueError("transaction filter values cannot contain duplicates")
        return values

    @field_validator("countries")
    @classmethod
    def validate_countries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(len(value) != 2 or not value.isascii() or not value.isupper() for value in values):
            raise ValueError("countries must be uppercase ISO-style alpha-2 codes")
        if len(values) != len(set(values)):
            raise ValueError("countries cannot contain duplicates")
        return values

    @field_validator("directions")
    @classmethod
    def validate_directions(
        cls,
        values: tuple[TransactionDirection, ...],
    ) -> tuple[TransactionDirection, ...]:
        if len(values) != len(set(values)):
            raise ValueError("directions cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_amount_range(self) -> "TransactionFilter":
        if (
            self.minimum_amount_minor is not None
            and self.maximum_amount_minor is not None
            and self.minimum_amount_minor > self.maximum_amount_minor
        ):
            raise ValueError("minimum_amount_minor cannot exceed maximum_amount_minor")
        return self


class FeatureRequest(FrozenContractModel):
    """Complete input to one deterministic feature operation."""

    operation: OperationName
    version: Version
    as_of: datetime
    window: FeatureWindow
    scope: EntityScope
    transaction_filter: TransactionFilter = Field(default_factory=TransactionFilter)
    group_by: tuple[FeatureGrouping, ...] = Field(default=(), max_length=7)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        return _require_utc(value, "as_of")

    @field_validator("group_by")
    @classmethod
    def validate_grouping(
        cls,
        values: tuple[FeatureGrouping, ...],
    ) -> tuple[FeatureGrouping, ...]:
        if len(values) != len(set(values)):
            raise ValueError("group_by cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_window_as_of(self) -> "FeatureRequest":
        if self.window.end_exclusive > self.as_of:
            raise ValueError("window end_exclusive cannot be after as_of")
        return self


class FeatureValue(FrozenContractModel):
    """One explicitly typed feature value; None records unavailable data."""

    name: OperationName
    value_type: ValueType
    value: ScalarValue | None
    unit: str | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_value_type(self) -> "FeatureValue":
        expected_types = {
            ValueType.INTEGER: int,
            ValueType.DECIMAL: Decimal,
            ValueType.FLOAT: float,
            ValueType.BOOLEAN: bool,
            ValueType.STRING: str,
        }
        if self.value is not None and type(self.value) is not expected_types[self.value_type]:
            raise ValueError(f"value must match declared value_type {self.value_type.value}")
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("numeric feature values must be finite")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("numeric feature values must be finite")
        return self


class FeatureDenominator(FrozenContractModel):
    """Named denominator used to interpret a ratio or rate."""

    name: OperationName
    value: int | Decimal = Field(ge=0)
    unit: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_finite(self) -> "FeatureDenominator":
        if isinstance(self.value, Decimal) and not self.value.is_finite():
            raise ValueError("denominator must be finite")
        return self


class FeatureWarning(FrozenContractModel):
    """Machine-readable feature quality or completeness warning."""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str = Field(min_length=1, max_length=500)


class FeatureProvenance(FrozenContractModel):
    """Data, implementation, and policy lineage for a feature result."""

    source: str = Field(min_length=1, max_length=128)
    dataset_version: Version
    operation_version: Version
    policy_version: Version | None = None
    query_id: Identifier | None = None


class FeatureResult(FrozenContractModel):
    """Typed output from one feature request."""

    request: FeatureRequest
    values: tuple[FeatureValue, ...]
    denominators: tuple[FeatureDenominator, ...] = ()
    warnings: tuple[FeatureWarning, ...] = Field(default=(), max_length=50)
    provenance: FeatureProvenance

    @model_validator(mode="after")
    def validate_result(self) -> "FeatureResult":
        names = [item.name for item in self.values]
        if len(names) != len(set(names)):
            raise ValueError("feature value names cannot contain duplicates")
        denominator_names = [item.name for item in self.denominators]
        if len(denominator_names) != len(set(denominator_names)):
            raise ValueError("feature denominator names cannot contain duplicates")
        if self.provenance.operation_version != self.request.version:
            raise ValueError("provenance operation_version must match request version")
        return self
