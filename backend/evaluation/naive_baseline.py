"""Evaluation-only fixed-threshold benchmark over label-free runtime data."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from backend.app.generation.contracts import RuntimeBundle, TransactionSeed


class _FrozenContract(BaseModel):
    """Strict, immutable Pydantic v2 contract for benchmark boundaries."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


class ThresholdProvenance(_FrozenContract):
    selection_data: Literal["development_scenarios"]
    frozen_before_evaluation: Literal[True]
    method: Literal["fixed_expert_benchmark"]
    notes: str = Field(min_length=1)


class NaiveBaselineConfig(_FrozenContract):
    version: Literal["naive_baseline.v1"]
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_threshold_minor: int = Field(ge=1)
    transactions_per_day_threshold: int = Field(ge=1)
    utc_day_semantics: Literal["occurred_at_utc_calendar_day"]
    amount_currency_handling: Literal["configured_currency_only_without_fx"]
    daily_count_currency_scope: Literal["all_currencies"]
    provenance: ThresholdProvenance


class AmountThresholdFlag(_FrozenContract):
    transaction_id: str
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class DailyCountThresholdFlag(_FrozenContract):
    customer_id: str
    utc_day: date
    transaction_count: int = Field(ge=1)
    transaction_ids: tuple[str, ...]


class CurrencyWarning(_FrozenContract):
    code: Literal["currency_excluded_from_amount_threshold"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    transaction_count: int = Field(ge=1)
    message: str


class NaiveBaselineResult(_FrozenContract):
    benchmark_version: Literal["naive_baseline.v1"]
    config_version: Literal["naive_baseline.v1"]
    source_run_id: str | None
    source_fingerprint: str | None
    amount_flags: tuple[AmountThresholdFlag, ...]
    daily_count_flags: tuple[DailyCountThresholdFlag, ...]
    warnings: tuple[CurrencyWarning, ...]


def load_naive_baseline_config(path: Path) -> NaiveBaselineConfig:
    """Load one strict, frozen benchmark configuration."""
    with path.open(encoding="utf-8") as handle:
        payload: Any = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain one YAML mapping")
    return NaiveBaselineConfig.model_validate(payload)


def apply_naive_baseline(
    data: RuntimeBundle | Sequence[TransactionSeed],
    config: NaiveBaselineConfig,
) -> NaiveBaselineResult:
    """Apply frozen thresholds without consuming labels or producing app alerts."""
    if isinstance(data, RuntimeBundle):
        transactions = tuple(data.transactions)
        source_run_id: str | None = data.run_id
        source_fingerprint: str | None = data.fingerprint
    else:
        transactions = tuple(data)
        source_run_id = None
        source_fingerprint = None

    if any(not isinstance(transaction, TransactionSeed) for transaction in transactions):
        raise TypeError("data must contain only label-free TransactionSeed instances")

    transaction_ids = [transaction.transaction_id for transaction in transactions]
    if len(transaction_ids) != len(set(transaction_ids)):
        raise ValueError("transaction IDs must be unique")

    ordered = sorted(
        transactions,
        key=lambda transaction: (
            transaction.occurred_at.astimezone(UTC),
            transaction.transaction_id,
        ),
    )
    amount_flags = tuple(
        AmountThresholdFlag(
            transaction_id=transaction.transaction_id,
            amount_minor=transaction.amount_minor,
            currency=transaction.currency,
        )
        for transaction in ordered
        if transaction.currency == config.currency
        and transaction.amount_minor >= config.amount_threshold_minor
    )

    daily_groups: dict[tuple[str, date], list[str]] = defaultdict(list)
    for transaction in ordered:
        utc_day = transaction.occurred_at.astimezone(UTC).date()
        daily_groups[(transaction.customer_id, utc_day)].append(transaction.transaction_id)
    daily_count_flags = tuple(
        DailyCountThresholdFlag(
            customer_id=customer_id,
            utc_day=utc_day,
            transaction_count=len(ids),
            transaction_ids=tuple(sorted(ids)),
        )
        for (customer_id, utc_day), ids in sorted(daily_groups.items())
        if len(ids) >= config.transactions_per_day_threshold
    )

    excluded_currencies = Counter(
        transaction.currency
        for transaction in transactions
        if transaction.currency != config.currency
    )
    warnings = tuple(
        CurrencyWarning(
            code="currency_excluded_from_amount_threshold",
            currency=currency,
            transaction_count=count,
            message=(
                f"{count} {currency} transaction(s) were excluded from the "
                f"{config.currency} amount threshold because no FX conversion is permitted; "
                "they remain included in all-currency daily counts."
            ),
        )
        for currency, count in sorted(excluded_currencies.items())
    )

    return NaiveBaselineResult(
        benchmark_version="naive_baseline.v1",
        config_version=config.version,
        source_run_id=source_run_id,
        source_fingerprint=source_fingerprint,
        amount_flags=amount_flags,
        daily_count_flags=daily_count_flags,
        warnings=warnings,
    )


__all__ = [
    "AmountThresholdFlag",
    "CurrencyWarning",
    "DailyCountThresholdFlag",
    "NaiveBaselineConfig",
    "NaiveBaselineResult",
    "ThresholdProvenance",
    "apply_naive_baseline",
    "load_naive_baseline_config",
]
