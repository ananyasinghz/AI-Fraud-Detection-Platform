"""Normalized query-filter contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.enums import PatternType

EntityId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class NormalizedFilters(ContractModel):
    """Explicit, bounded scope shared by all tools."""

    date_from: datetime | None = None
    date_to: datetime | None = None
    customer_ids: list[EntityId] = Field(default_factory=list, max_length=100)
    account_ids: list[EntityId] = Field(default_factory=list, max_length=100)
    transaction_ids: list[EntityId] = Field(default_factory=list, max_length=100)
    segment: str | None = Field(default=None, min_length=1, max_length=64)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    transaction_type: str | None = Field(default=None, min_length=1, max_length=64)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    pattern_type: PatternType | None = None
    amount_min: Decimal | None = Field(default=None, ge=0)
    amount_max: Decimal | None = Field(default=None, ge=0)
    max_results: int = Field(default=100, ge=1, le=1000)

    @field_validator("date_from", "date_to")
    @classmethod
    def validate_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and not is_timezone_aware(value):
            raise ValueError("filter datetimes must include a timezone")
        return value

    @field_validator("customer_ids", "account_ids", "transaction_ids")
    @classmethod
    def validate_unique_ids(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("entity ID lists cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_ranges(self) -> "NormalizedFilters":
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        if (
            self.amount_min is not None
            and self.amount_max is not None
            and self.amount_min > self.amount_max
        ):
            raise ValueError("amount_min cannot exceed amount_max")
        return self
