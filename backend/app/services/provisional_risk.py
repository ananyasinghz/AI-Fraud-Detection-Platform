"""Provisional Phase 3 alert risk placeholders (not Phase 8 calibrated risk)."""

from __future__ import annotations

from typing import Literal

from backend.app.domain.enums import EscalationAction, RiskLevel

Severity = Literal["low", "medium", "high", "critical"]


def provisional_risk_from_severity(
    severity: Severity,
) -> tuple[float, RiskLevel, EscalationAction]:
    """Map anomaly-signal severity to schema-required risk fields.

    These values are explicit placeholders for lifecycle APIs until Phase 8
    risk classification lands. They are not calibrated risk scores.
    """
    mapping: dict[Severity, tuple[float, RiskLevel, EscalationAction]] = {
        "low": (0.25, RiskLevel.LOW, EscalationAction.MONITOR),
        "medium": (0.50, RiskLevel.MEDIUM, EscalationAction.REVIEW),
        "high": (0.75, RiskLevel.HIGH, EscalationAction.REVIEW),
        "critical": (0.90, RiskLevel.HIGH, EscalationAction.REPORT),
    }
    return mapping[severity]
