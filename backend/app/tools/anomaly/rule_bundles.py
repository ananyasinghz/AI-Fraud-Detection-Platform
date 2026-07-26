"""Per-rule FeatureRequest bundles for multi-rule anomaly evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.app.domain.enums import EntityType, TransactionDirection
from backend.app.domain.features import (
    EntityScope,
    FeatureRequest,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.policy.config import PolicyConfig

# rule_id → operations evaluated together for that rule's RuleInput
RULE_FEATURE_OPS: dict[str, tuple[str, ...]] = {
    "structuring.v1": ("subthreshold_count",),
    "smurfing.v1": ("transaction_count", "distinct_counterparties"),
    "velocity.v1": ("rolling_count",),
    "rapid_cash_out.v1": ("rapid_cash_out_ratio",),
    "round_numbers.v1": ("transaction_count", "round_number_ratio"),
    "profile_deviation.v1": (
        "data_sufficiency",
        "transaction_count",
        "transaction_total",
        "activity_vs_expected",
    ),
    "high_risk_country.v1": ("transaction_count", "transaction_total"),
}


def rule_window(rule_id: str, policy: PolicyConfig) -> timedelta:
    """Exact half-open window length required by each deterministic rule."""
    if rule_id == "structuring.v1":
        return timedelta(days=policy.structuring.window_days)
    if rule_id == "smurfing.v1":
        return timedelta(hours=policy.smurfing.window_hours)
    if rule_id == "velocity.v1":
        return timedelta(minutes=policy.velocity.window_minutes)
    if rule_id == "rapid_cash_out.v1":
        return timedelta(minutes=policy.rapid_cash_out.window_minutes)
    if rule_id == "round_numbers.v1":
        return timedelta(days=policy.round_numbers.window_days)
    if rule_id == "profile_deviation.v1":
        return timedelta(days=policy.profile_deviation.window_days)
    if rule_id == "high_risk_country.v1":
        return timedelta(days=policy.high_risk_country.window_days)
    raise ValueError(f"unknown rule for window: {rule_id}")


def rule_transaction_filter(rule_id: str, policy: PolicyConfig) -> TransactionFilter:
    """Scope predicates required by rule validate_requests checks."""
    if rule_id == "smurfing.v1":
        return TransactionFilter(
            directions=(TransactionDirection.CREDIT,),
            currency=policy.currency,
        )
    if rule_id == "high_risk_country.v1":
        return TransactionFilter(
            countries=tuple(policy.high_risk_countries),
            currency=policy.currency,
        )
    if rule_id in {
        "structuring.v1",
        "rapid_cash_out.v1",
        "round_numbers.v1",
        "profile_deviation.v1",
    }:
        return TransactionFilter(currency=policy.currency)
    # velocity.v1: no currency requirement on the rule
    return TransactionFilter()


def build_rule_feature_requests(
    *,
    rule_id: str,
    entity_id: str,
    as_of: datetime,
    policy: PolicyConfig,
) -> tuple[FeatureRequest, ...]:
    """Build FeatureRequests with policy-exact windows for one rule."""
    operations = RULE_FEATURE_OPS.get(rule_id)
    if operations is None:
        raise ValueError(f"no feature ops registered for rule: {rule_id}")
    window = rule_window(rule_id, policy)
    txn_filter = rule_transaction_filter(rule_id, policy)
    scope = EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=(entity_id,))
    feature_window = FeatureWindow(
        start_inclusive=as_of - window,
        end_exclusive=as_of,
    )
    return tuple(
        FeatureRequest(
            operation=operation,
            version="v1",
            as_of=as_of,
            window=feature_window,
            scope=scope,
            transaction_filter=txn_filter,
        )
        for operation in operations
    )
