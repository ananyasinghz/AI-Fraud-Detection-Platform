"""Versioned, jurisdiction-aware detection policy contracts and loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.app.domain.base import ContractModel


class PolicyContractModel(ContractModel):
    """Frozen base for policy loaded once and shared across detectors."""

    model_config = ConfigDict(frozen=True)


class StructuringPolicy(PolicyContractModel):
    version: str
    window_days: int = Field(ge=1)
    minimum_count: int = Field(ge=2)
    lower_bound_ratio: float = Field(gt=0, lt=1)
    upper_bound_ratio: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_ratio_range(self) -> "StructuringPolicy":
        if self.lower_bound_ratio >= self.upper_bound_ratio:
            raise ValueError("lower_bound_ratio must be less than upper_bound_ratio")
        return self


class SmurfingPolicy(PolicyContractModel):
    version: str
    window_hours: int = Field(ge=1)
    minimum_transactions: int = Field(ge=2)
    minimum_distinct_senders: int = Field(ge=2)


class VelocityPolicy(PolicyContractModel):
    version: str
    window_minutes: int = Field(ge=1)
    minimum_transaction_count: int = Field(ge=2)


class RapidCashOutPolicy(PolicyContractModel):
    version: str
    window_minutes: int = Field(ge=1)
    minimum_inflow_minor: int = Field(gt=0)
    minimum_cash_out_ratio: float = Field(gt=0, le=1)


class RoundNumberPolicy(PolicyContractModel):
    version: str
    window_days: int = Field(ge=1)
    minimum_transaction_count: int = Field(ge=1)
    minimum_round_number_ratio: float = Field(gt=0, le=1)
    rounding_increment_minor: int = Field(gt=0)


class ProfileDeviationPolicy(PolicyContractModel):
    version: str
    window_days: int = Field(ge=1)
    minimum_transaction_count: int = Field(ge=1)
    minimum_observed_volume_minor: int = Field(gt=0)
    minimum_expected_volume_ratio: float = Field(gt=1)


class HighRiskCountryPolicy(PolicyContractModel):
    version: str
    window_days: int = Field(ge=1)
    minimum_transaction_count: int = Field(ge=1)
    minimum_total_minor: int = Field(gt=0)


class DataSufficiencyPolicy(PolicyContractModel):
    version: str
    minimum_transactions: int = Field(ge=1)
    minimum_history_days: int = Field(ge=1)
    minimum_baseline_transactions: int = Field(ge=1)


class PolicyConfig(PolicyContractModel):
    """All deterministic thresholds for one jurisdiction and currency."""

    version: str
    jurisdiction: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9-]+$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reporting_threshold_minor: int = Field(gt=0)
    structuring: StructuringPolicy
    smurfing: SmurfingPolicy
    velocity: VelocityPolicy
    rapid_cash_out: RapidCashOutPolicy
    round_numbers: RoundNumberPolicy
    profile_deviation: ProfileDeviationPolicy
    high_risk_country: HighRiskCountryPolicy
    high_risk_countries: tuple[str, ...] = Field(min_length=1)
    data_sufficiency: DataSufficiencyPolicy
    disclaimer: str = Field(min_length=1, max_length=500)

    @field_validator("high_risk_countries")
    @classmethod
    def validate_high_risk_countries(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("high_risk_countries cannot contain duplicates")
        if any(len(value) != 2 or not value.isascii() or not value.isupper() for value in values):
            raise ValueError("high_risk_countries must contain uppercase alpha-2 codes")
        return values


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return value


def load_policy_config(path: Path) -> PolicyConfig:
    """Load and validate one shared detection policy file."""

    return PolicyConfig.model_validate(_read_yaml(path))


__all__ = [
    "DataSufficiencyPolicy",
    "HighRiskCountryPolicy",
    "PolicyConfig",
    "ProfileDeviationPolicy",
    "RapidCashOutPolicy",
    "RoundNumberPolicy",
    "SmurfingPolicy",
    "StructuringPolicy",
    "VelocityPolicy",
    "load_policy_config",
]
