"""Points-model transaction risk classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.enums import RiskLevel
from backend.app.risk.policy import RiskScoringPolicy, TierBounds


@dataclass
class RiskClassificationResult:
    entity_type: str
    entity_id: str
    risk_score: float
    risk_level: RiskLevel
    confidence: float
    ml_score: float | None
    contributing_signals: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    policy_version: str = ""
    evidence_ids: list[str] = field(default_factory=list)


def tier_from_score(score: float, tiers: TierBounds) -> RiskLevel:
    if score < tiers.low_max_exclusive:
        return RiskLevel.LOW
    if score < tiers.medium_max_exclusive:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def classify_transaction_risk(
    *,
    entity_id: str,
    anomaly_payload: dict[str, Any],
    graph_findings: list[dict[str, Any]],
    policy: RiskScoringPolicy,
    evidence_ids: list[str],
    confidence_cap: float | None = None,
    insufficient_data: bool = False,
) -> RiskClassificationResult:
    points = 0.0
    signals: list[dict[str, Any]] = []
    reasons: list[str] = []
    warnings: list[str] = []
    ml_score: float | None = None

    rules = anomaly_payload.get("rules") or []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            fired = bool(rule.get("fired", True))
            if not fired:
                continue
            severity = str(rule.get("severity") or rule.get("severity_level") or "medium").lower()
            pts = float(
                policy.severity_points.get(severity, policy.severity_points.get("medium", 35))
            )
            points += pts
            rule_id = str(rule.get("rule_id") or rule.get("rule") or "rule")
            signals.append(
                {"type": "rule", "rule_id": rule_id, "severity": severity, "points": pts}
            )
            reasons.append(f"Rule {rule_id} fired ({severity}, +{pts:.0f})")

    stats = anomaly_payload.get("statistics") or {}
    if (
        isinstance(stats, dict)
        and stats
        and any(key in stats for key in ("robust_z", "mad", "outlier", "iqr"))
    ):
        pts = float(policy.signal_points.get("statistical_anomaly", 20))
        points += pts
        signals.append({"type": "statistical", "points": pts})
        reasons.append(f"Statistical anomaly signal (+{pts:.0f})")

    ml = anomaly_payload.get("ml")
    if isinstance(ml, dict) and ml.get("ml_score") is not None:
        try:
            ml_score = float(ml["ml_score"])
        except (TypeError, ValueError):
            ml_score = None
        if ml_score is not None and ml_score >= policy.ml_flag_threshold:
            pts = float(policy.signal_points.get("ml_threshold_cross", 25))
            points += pts
            signals.append({"type": "ml", "ml_score": ml_score, "points": pts})
            reasons.append(f"ML score {ml_score:.3f} crossed threshold (+{pts:.0f})")

    for finding in graph_findings:
        op = str(finding.get("operation") or "")
        if op == "shared_device" or "customer_ids" in finding:
            pts = float(policy.signal_points.get("graph_shared_device", 20))
            key = "graph_shared_device"
        elif op == "circular_transfers" or "cycles" in finding:
            pts = float(policy.signal_points.get("graph_circular_transfer", 30))
            key = "graph_circular_transfer"
        elif op == "two_hop_exposure":
            pts = float(policy.signal_points.get("graph_two_hop", 15))
            key = "graph_two_hop"
        else:
            continue
        points += pts
        signals.append({"type": "graph", "signal": key, "points": pts})
        reasons.append(f"Graph signal {key} (+{pts:.0f})")

    if insufficient_data:
        penalty = float(policy.data_sufficiency.insufficient_penalty)
        points = max(0.0, points - penalty)
        warnings.append("INSUFFICIENT_DATA_PENALTY")
        confidence = min(
            policy.data_sufficiency.insufficient_confidence_cap,
            policy.data_sufficiency.reduced_confidence,
        )
    else:
        confidence = (
            policy.data_sufficiency.full_confidence
            if signals
            else policy.data_sufficiency.reduced_confidence
        )

    if confidence_cap is not None:
        confidence = min(confidence, confidence_cap)

    risk_score = max(0.0, min(100.0, points))
    level = tier_from_score(risk_score, policy.tiers)
    if not reasons:
        reasons.append("No material anomaly or graph signals; baseline low risk.")
        warnings.append("NO_MATERIAL_SIGNALS")

    return RiskClassificationResult(
        entity_type="transaction",
        entity_id=entity_id,
        risk_score=risk_score,
        risk_level=level,
        confidence=float(confidence),
        ml_score=ml_score,
        contributing_signals=signals,
        reasons=reasons[:20],
        warnings=warnings,
        policy_version=policy.version,
        evidence_ids=evidence_ids,
    )
