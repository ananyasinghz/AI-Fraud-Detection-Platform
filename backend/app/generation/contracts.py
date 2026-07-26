"""Serializable contracts used by offline scenario generation and seeding."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from backend.app.domain.base import ContractModel


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("scenario datetimes must include a timezone")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_require_aware)]
ScenarioType = Literal[
    "clean_control",
    "structuring",
    "smurfing",
    "velocity",
    "rapid_cash_out",
    "round_number",
    "spending_increase",
    "profile_deviation",
    "new_account",
    "high_risk_country",
    "graph_relationship",
]


class CustomerSeed(ContractModel):
    customer_id: str
    created_at: AwareDatetime
    status: Literal["active", "inactive", "closed"] = "active"


class CustomerProfileSeed(ContractModel):
    customer_id: str
    segment: Literal["retail", "sme", "corporate"]
    residence_country: str = Field(pattern=r"^[A-Z]{2}$")
    occupation_or_industry: str | None = None
    declared_annual_income_minor: int | None = Field(default=None, ge=0)
    declared_revenue_band: str | None = None
    income_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    expected_monthly_volume_min_minor: int | None = Field(default=None, ge=0)
    expected_monthly_volume_max_minor: int | None = Field(default=None, ge=0)
    volume_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    kyc_risk_rating: Literal["low", "medium", "high"] | None = None
    pep_flag: bool = False
    profile_effective_from: AwareDatetime
    profile_effective_to: AwareDatetime | None = None
    profile_source: str = "synthetic_generator.v1"


class AccountSeed(ContractModel):
    account_id: str
    customer_id: str
    account_type: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    opened_at: AwareDatetime
    status: Literal["active", "inactive", "closed"] = "active"


class CounterpartySeed(ContractModel):
    counterparty_id: str
    display_name: str
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    kind: str | None = None


class DeviceSeed(ContractModel):
    device_id: str
    device_type: str
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime


class TransactionSeed(ContractModel):
    transaction_id: str
    account_id: str
    customer_id: str
    occurred_at: AwareDatetime
    posted_at: AwareDatetime | None = None
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    direction: Literal["credit", "debit"]
    transaction_type: str
    channel: str
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    counterparty_id: str | None = None
    counterparty_account_id: str | None = None
    device_id: str | None = None
    ml_eligible: Literal[False] = False
    ml_feature_ref: None = None
    data_source: Literal["synthetic"] = "synthetic"


class RuntimeBundle(ContractModel):
    run_id: str
    seed: int
    split: Literal["dev", "held_out", "ci_tiny"]
    generator_version: str
    policy_version: str
    generated_at: AwareDatetime
    customers: list[CustomerSeed]
    profiles: list[CustomerProfileSeed]
    accounts: list[AccountSeed]
    counterparties: list[CounterpartySeed]
    devices: list[DeviceSeed]
    transactions: list[TransactionSeed]
    fingerprint: str


class ScenarioAnnotation(ContractModel):
    scenario_id: str
    pattern_type: ScenarioType
    entity_type: Literal["customer", "account", "transaction"]
    entity_id: str
    window_from: AwareDatetime
    window_to: AwareDatetime
    expected_signals: list[str]
    notes: str


class GenerationResult(ContractModel):
    runtime: RuntimeBundle
    annotations: list[ScenarioAnnotation]
