"""PatternType → feature ops + rule_ids for typology-aware pattern_search plans."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.enums import PatternType


@dataclass(frozen=True)
class PatternPlanSpec:
    """Deterministic feature/rule selection for one AML typology."""

    pattern: PatternType
    feature_operations: tuple[str, ...]
    rule_ids: tuple[str, ...] | None
    window_days: int
    reason: str

    @property
    def strategy(self) -> str:
        return f"pattern_{self.pattern.value}"


_SPECS: dict[PatternType, PatternPlanSpec] = {
    PatternType.STRUCTURING: PatternPlanSpec(
        pattern=PatternType.STRUCTURING,
        feature_operations=("subthreshold_count",),
        rule_ids=("structuring.v1",),
        window_days=30,
        reason="structuring subthreshold feature support",
    ),
    PatternType.SMURFING: PatternPlanSpec(
        pattern=PatternType.SMURFING,
        feature_operations=("transaction_count", "distinct_counterparties"),
        rule_ids=("smurfing.v1",),
        window_days=30,
        reason="smurfing inbound count and distinct counterparty features",
    ),
    PatternType.VELOCITY: PatternPlanSpec(
        pattern=PatternType.VELOCITY,
        feature_operations=("rolling_count",),
        rule_ids=("velocity.v1",),
        window_days=30,
        reason="velocity rolling-count feature support",
    ),
    PatternType.RAPID_CASH_OUT: PatternPlanSpec(
        pattern=PatternType.RAPID_CASH_OUT,
        feature_operations=("rapid_cash_out_ratio",),
        rule_ids=("rapid_cash_out.v1",),
        window_days=30,
        reason="rapid cash-out ratio feature support",
    ),
    PatternType.ROUND_NUMBER: PatternPlanSpec(
        pattern=PatternType.ROUND_NUMBER,
        feature_operations=("round_number_ratio",),
        rule_ids=("round_numbers.v1",),
        window_days=30,
        reason="round-number ratio feature support",
    ),
    PatternType.PROFILE_DEVIATION: PatternPlanSpec(
        pattern=PatternType.PROFILE_DEVIATION,
        feature_operations=("activity_vs_expected",),
        rule_ids=("profile_deviation.v1",),
        window_days=30,
        reason="profile deviation activity feature support",
    ),
    PatternType.HIGH_RISK_COUNTRY: PatternPlanSpec(
        pattern=PatternType.HIGH_RISK_COUNTRY,
        feature_operations=("transaction_total",),
        rule_ids=("high_risk_country.v1",),
        window_days=30,
        reason="high-risk country volume feature support",
    ),
    PatternType.GENERAL: PatternPlanSpec(
        pattern=PatternType.GENERAL,
        feature_operations=("transaction_count",),
        rule_ids=None,
        window_days=30,
        reason="general pattern search; anomaly evaluates all rules",
    ),
}


def spec_for_pattern(pattern: PatternType | None) -> PatternPlanSpec:
    """Resolve a plan spec; missing/unknown patterns use the general multi-rule path."""
    if pattern is None:
        return _SPECS[PatternType.GENERAL]
    return _SPECS.get(pattern, _SPECS[PatternType.GENERAL])


__all__ = ["PatternPlanSpec", "spec_for_pattern"]
