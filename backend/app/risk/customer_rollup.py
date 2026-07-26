"""Customer-level risk rollup (customer_rollup.v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.enums import RiskLevel
from backend.app.risk.classifier import tier_from_score
from backend.app.risk.policy import RiskScoringPolicy


@dataclass
class CustomerRollupResult:
    entity_id: str
    risk_score: float
    risk_level: RiskLevel
    confidence: float
    event_peak: float
    pattern_breadth: float
    profile_score: float
    context_score: float
    composite: float
    contributing_transaction_ids: list[str] = field(default_factory=list)
    contributing_rule_ids: list[str] = field(default_factory=list)
    decay_values: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    rollup_method: str = "customer_rollup.v1"
    policy_version: str = ""
    evidence_ids: list[str] = field(default_factory=list)


def recency_decay(age_days: float, *, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    return float(0.5 ** (age_days / half_life_days))


def rollup_customer_risk(
    *,
    customer_id: str,
    transaction_risks: list[dict[str, Any]],
    rule_events: list[dict[str, Any]],
    profile_score: float | None,
    context_score: float | None,
    policy: RiskScoringPolicy,
    evidence_ids: list[str],
) -> CustomerRollupResult:
    """Transparent aggregation over lookback window (roadmap formula)."""
    cfg = policy.customer_rollup
    warnings: list[str] = []
    reasons: list[str] = []

    scores = [float(item.get("risk_score") or 0) for item in transaction_risks]
    event_peak = max(scores) if scores else 0.0
    txn_ids = [
        str(item["transaction_id"]) for item in transaction_risks if item.get("transaction_id")
    ]

    # Unique rules with recency decay; duplicate rule IDs suppressed (max contribution kept).
    by_rule: dict[str, float] = {}
    decay_values: dict[str, float] = {}
    for event in rule_events:
        rule_id = str(event.get("rule_id") or "rule")
        severity = str(event.get("severity") or "medium").lower()
        base = float(cfg.rule_base_points.get(severity, 20))
        age_days = float(event.get("age_days") or 0)
        decay = recency_decay(age_days, half_life_days=float(cfg.half_life_days))
        contribution = base * decay
        decay_values[rule_id] = decay
        by_rule[rule_id] = max(by_rule.get(rule_id, 0.0), contribution)

    pattern_breadth = min(100.0, sum(by_rule.values()))
    rule_ids = sorted(by_rule)

    if profile_score is None:
        profile = 0.0
        warnings.append("PROFILE_SCORE_MISSING")
    else:
        profile = max(0.0, min(float(cfg.profile_score_cap), float(profile_score)))

    if context_score is None:
        context = 0.0
        warnings.append("CONTEXT_SCORE_MISSING")
    else:
        context = max(0.0, min(float(cfg.context_score_cap), float(context_score)))

    w = cfg.weights
    composite = (
        w.event_peak * event_peak
        + w.pattern_breadth * pattern_breadth
        + w.profile_score * profile
        + w.context_score * context
    )
    customer_risk_score = max(event_peak, composite)
    level = tier_from_score(customer_risk_score, policy.tiers)

    # Context cannot independently force a suspicious tier.
    if cfg.context_cannot_force_suspicious and level is not RiskLevel.LOW:
        without_context = (
            w.event_peak * event_peak
            + w.pattern_breadth * pattern_breadth
            + w.profile_score * profile
        )
        peak_or_comp = max(event_peak, without_context)
        level_without = tier_from_score(peak_or_comp, policy.tiers)
        if level_without is RiskLevel.LOW and event_peak < policy.tiers.low_max_exclusive:
            warnings.append("CONTEXT_ONLY_SUSPICIOUS_BLOCKED")
            customer_risk_score = min(customer_risk_score, policy.tiers.low_max_exclusive - 0.01)
            level = RiskLevel.LOW
            reasons.append("KYC/context capped; cannot independently assert suspicious tier.")

    if event_peak >= policy.tiers.medium_max_exclusive:
        reasons.append(f"Severe event_peak={event_peak:.1f} drives customer risk.")
    if pattern_breadth >= policy.tiers.low_max_exclusive:
        reasons.append(f"Pattern breadth={pattern_breadth:.1f} from unique rules with decay.")
    if not reasons:
        reasons.append("Customer rollup within low-risk band.")

    confidence = 0.8 if (scores or by_rule) else 0.5
    if "PROFILE_SCORE_MISSING" in warnings:
        confidence = min(confidence, 0.6)

    return CustomerRollupResult(
        entity_id=customer_id,
        risk_score=max(0.0, min(100.0, customer_risk_score)),
        risk_level=level,
        confidence=confidence,
        event_peak=event_peak,
        pattern_breadth=pattern_breadth,
        profile_score=profile,
        context_score=context,
        composite=composite,
        contributing_transaction_ids=txn_ids,
        contributing_rule_ids=rule_ids,
        decay_values=decay_values,
        warnings=warnings,
        reasons=reasons[:20],
        rollup_method=cfg.version,
        policy_version=policy.version,
        evidence_ids=evidence_ids,
    )
