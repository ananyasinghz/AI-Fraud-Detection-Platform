"""Stage 2 risk consistency verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.enums import RiskLevel
from backend.app.risk.classifier import tier_from_score
from backend.app.risk.policy import RiskScoringPolicy


@dataclass
class ConsistencyResult:
    ok: bool
    risk_score: float
    risk_level: RiskLevel
    confidence: float
    action: str  # pass | downgrade | reject
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def verify_risk_consistency(
    *,
    risk_score: float,
    risk_level: RiskLevel,
    confidence: float,
    contributing_signals: list[dict[str, Any]],
    policy: RiskScoringPolicy,
    context_only: bool = False,
    insufficient_data: bool = False,
    ml_score: float | None = None,
) -> ConsistencyResult:
    """Independently check score/tier reproducibility and policy constraints."""
    warnings: list[str] = []
    expected_level = tier_from_score(risk_score, policy.tiers)
    if expected_level is not risk_level:
        warnings.append("TIER_MISMATCH_RECOMPUTED")
        risk_level = expected_level

    # Validate weights sum for rollup awareness (informational).
    weights = policy.customer_rollup.weights
    weight_sum = (
        weights.event_peak + weights.pattern_breadth + weights.profile_score + weights.context_score
    )
    if abs(weight_sum - 1.0) > 0.01:
        warnings.append("INVALID_ROLLUP_WEIGHTS")
        return ConsistencyResult(
            ok=False,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            action="reject",
            warnings=warnings,
            details={"weight_sum": weight_sum},
        )

    if context_only and risk_level is not RiskLevel.LOW:
        warnings.append("CONTEXT_ONLY_TIER_DOWNGRADE")
        risk_score = min(risk_score, policy.tiers.low_max_exclusive - 0.01)
        risk_level = RiskLevel.LOW
        return ConsistencyResult(
            ok=True,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=min(confidence, 0.5),
            action="downgrade",
            warnings=warnings,
        )

    if insufficient_data and risk_level is RiskLevel.HIGH:
        # High severity with weak data → downgrade to MEDIUM for review queue posture.
        warnings.append("HIGH_WITH_WEAK_DATA_DOWNGRADE")
        risk_level = RiskLevel.MEDIUM
        risk_score = min(risk_score, policy.tiers.medium_max_exclusive - 0.01)
        confidence = min(confidence, policy.data_sufficiency.insufficient_confidence_cap)
        return ConsistencyResult(
            ok=True,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            action="downgrade",
            warnings=warnings,
        )

    # Surface ML/rule conflicts in confidence.
    has_rule = any(item.get("type") == "rule" for item in contributing_signals)
    has_ml = any(item.get("type") == "ml" for item in contributing_signals)
    if has_rule and has_ml and ml_score is not None and ml_score < policy.ml_flag_threshold:
        warnings.append("ML_RULE_CONFLICT")
        confidence = min(confidence, 0.6)

    if risk_score < 0 or risk_score > 100:
        warnings.append("SCORE_OUT_OF_BOUNDS")
        return ConsistencyResult(
            ok=False,
            risk_score=risk_score,
            risk_level=risk_level,
            confidence=confidence,
            action="reject",
            warnings=warnings,
        )

    return ConsistencyResult(
        ok=True,
        risk_score=risk_score,
        risk_level=risk_level,
        confidence=confidence,
        action="pass",
        warnings=warnings,
    )
