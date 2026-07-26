"""Deterministic explanation templates (Ollama-down path)."""

from __future__ import annotations

from typing import Any


def render_explanation(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a grounded explanation from verified risk/escalation fields only."""
    entity_id = str(payload.get("entity_id") or "unknown")
    risk_level = str(payload.get("risk_level") or "LOW")
    risk_score = float(payload.get("risk_score") or 0)
    confidence = float(payload.get("confidence") or 0)
    action = str(payload.get("escalation_action") or "monitor")
    reasons = [str(item) for item in (payload.get("reasons") or [])][:10]
    evidence_ids = [str(item) for item in (payload.get("evidence_ids") or [])][:20]
    warnings = [str(item) for item in (payload.get("warnings") or [])]

    summary = (
        f"Entity {entity_id} assessed at {risk_level} "
        f"(score={risk_score:.1f}/100, confidence={confidence:.2f})."
    )
    action_text = {
        "monitor": "Recommended next action: monitor per institutional policy.",
        "review": "Recommended next action: queue for analyst review per institutional policy.",
        "report": (
            "Recommended next action: prepare/escalate for reporting "
            "according to institutional policy (not a legal filing mandate)."
        ),
    }.get(action, f"Recommended next action: {action}.")

    uncertainty = "No material data-sufficiency warnings."
    if warnings:
        uncertainty = "Uncertainty/missing-data notes: " + "; ".join(warnings[:5])

    claims = []
    for index, reason in enumerate(reasons):
        claim_evidence = [evidence_ids[index]] if index < len(evidence_ids) else evidence_ids[:1]
        claims.append({"claim": reason, "evidence_ids": claim_evidence or ["none"]})

    return {
        "summary": summary,
        "reasons": reasons,
        "risk_level_explanation": (
            f"Risk level {risk_level} follows the versioned points/rollup policy "
            f"(score {risk_score:.1f}). ml_score is separate from risk_score."
        ),
        "recommended_action_explanation": action_text,
        "uncertainty_note": uncertainty,
        "evidence_ids": evidence_ids,
        "claims": claims,
        "source": "template",
    }
