"""Deterministic escalation mapping and alert snapshot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.app.domain.enums import EscalationAction, RiskLevel
from backend.app.risk.policy import RiskScoringPolicy


@dataclass(frozen=True)
class EscalationRecommendation:
    risk_level: RiskLevel
    escalation_action: EscalationAction
    wording: str
    should_create_alert: bool
    finding_code: str
    snapshot: dict[str, Any]


def map_escalation(risk_level: RiskLevel, policy: RiskScoringPolicy) -> EscalationAction:
    raw = policy.escalation.get(risk_level.value) or policy.escalation.get(risk_level.name)
    if raw is None:
        # Fallback to roadmap defaults.
        return {
            RiskLevel.LOW: EscalationAction.MONITOR,
            RiskLevel.MEDIUM: EscalationAction.REVIEW,
            RiskLevel.HIGH: EscalationAction.REPORT,
        }[risk_level]
    return EscalationAction(str(raw).lower())


def recommend_escalation(
    *,
    entity_type: str,
    entity_id: str,
    risk_score: float,
    risk_level: RiskLevel,
    confidence: float,
    reasons: list[str],
    evidence_ids: list[str],
    policy: RiskScoringPolicy,
    window_start: datetime,
    window_end: datetime,
) -> EscalationRecommendation:
    action = map_escalation(risk_level, policy)
    wording = {
        EscalationAction.MONITOR: (
            "Recommend continued monitoring according to institutional policy."
        ),
        EscalationAction.REVIEW: ("Recommend analyst review according to institutional policy."),
        EscalationAction.REPORT: (
            "Recommend preparing/escalating for reporting according to institutional policy."
        ),
    }[action]
    snapshot = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "risk_score": risk_score,
        "risk_level": risk_level.value,
        "confidence": confidence,
        "reasons": reasons,
        "evidence_ids": evidence_ids,
        "escalation_action": action.value,
        "policy_version": policy.version,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "disclaimer": policy.disclaimer.strip(),
    }
    return EscalationRecommendation(
        risk_level=risk_level,
        escalation_action=action,
        wording=wording,
        should_create_alert=action in {EscalationAction.REVIEW, EscalationAction.REPORT},
        finding_code=f"PHASE8_{risk_level.value}",
        snapshot=snapshot,
    )
