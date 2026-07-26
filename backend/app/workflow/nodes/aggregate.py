"""Aggregate node: build FinalResponse from execution state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import EntityType, EscalationAction, RiskLevel, ToolName, ToolStatus
from backend.app.domain.evidence import ToolResult
from backend.app.domain.responses import (
    ExecutionSummary,
    FinalResponse,
    FlaggedResult,
    InformationalResult,
    ResultItem,
)
from backend.app.workflow.execution_trace import ExecutionTrace
from backend.app.workflow.state import InvestigationState


def build_final_response(
    state: InvestigationState,
    trace: ExecutionTrace,
    *,
    status: str,
) -> FinalResponse:
    summary = trace.build_summary(state)
    charts = _extract_charts(state.tool_results)
    flagged = _extract_flagged_results(state.tool_results)
    results: list[ResultItem] = list(flagged)
    if not flagged:
        info_summary, info_data = _informational_payload(state, status, charts)
        results.append(
            InformationalResult(
                summary=info_summary,
                data=info_data,
                evidence_refs=list(state.evidence_refs),
            )
        )
    elif status != "completed":
        results.insert(
            0,
            InformationalResult(
                summary=_default_informational_summary(state, status),
                data={"status": status},
                evidence_refs=list(state.evidence_refs),
            ),
        )
    answer = _answer_text(state, summary, status, flagged)
    return FinalResponse(
        request_id=state.request_id,
        generated_at=datetime.now(tz=UTC),
        execution_summary=summary,
        results=results,
        supporting_evidence=list(state.tool_results),
        charts=charts,
        answer=answer,
    )


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_float(value: object, default: float) -> float:
    try:
        return float(value) if value is not None else default  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _extract_flagged_results(results: list[ToolResult]) -> list[FlaggedResult]:
    """Emit FlaggedResult only from dual-verified risk + escalation payloads."""
    consistency = _latest(
        results,
        tool=ToolName.VERIFICATION,
        operation="verify_risk_consistency",
    )
    escalation = _latest(results, tool=ToolName.ESCALATION, operation="recommend")
    if consistency is None or escalation is None:
        return []
    if consistency.status is not ToolStatus.SUCCESS or escalation.status is not ToolStatus.SUCCESS:
        return []

    risk_level = RiskLevel(str(consistency.data.get("risk_level") or "LOW"))
    explanation = _latest(results, tool=ToolName.EXPLANATION, operation="explain")
    low_requested = explanation is not None and explanation.status is ToolStatus.SUCCESS
    if risk_level is RiskLevel.LOW and not low_requested:
        return []

    entity_raw = str(
        escalation.data.get("entity_type") or consistency.data.get("entity_type") or "customer"
    )
    try:
        entity_type = EntityType(entity_raw)
    except ValueError:
        entity_type = EntityType.CUSTOMER

    entity_id = str(
        escalation.data.get("entity_id") or consistency.data.get("entity_id") or "UNKNOWN"
    )
    reasons = _as_str_list(escalation.data.get("reasons") or consistency.data.get("reasons"))
    if not reasons:
        reasons = ["Verified risk assessment completed."]
    evidence_refs = _as_str_list(
        escalation.data.get("evidence_ids") or consistency.data.get("evidence_ids")
    )
    if not evidence_refs:
        evidence_refs = [f"phase8:{entity_id}"]

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_refs: list[str] = []
    for ref in evidence_refs:
        if ref in seen:
            continue
        seen.add(ref)
        unique_refs.append(ref)

    action = EscalationAction(str(escalation.data.get("escalation_action") or "monitor").lower())
    return [
        FlaggedResult(
            entity_type=entity_type,
            entity_id=entity_id,
            risk_score=_as_float(consistency.data.get("risk_score"), 0.0),
            risk_level=risk_level,
            confidence=_as_float(consistency.data.get("confidence"), 0.5),
            reasons=reasons[:20],
            escalation_action=action,
            evidence_refs=unique_refs[:100],
        )
    ]


def _latest(
    results: list[ToolResult],
    *,
    tool: ToolName,
    operation: str,
) -> ToolResult | None:
    for result in reversed(results):
        if result.tool is tool and result.operation == operation:
            return result
    return None


def _extract_charts(results: list[ToolResult]) -> list[ChartSpec]:
    charts: list[ChartSpec] = []
    for result in results:
        raw_charts = result.data.get("charts")
        if not isinstance(raw_charts, list):
            continue
        for item in raw_charts:
            if isinstance(item, dict):
                charts.append(ChartSpec.model_validate(item))
    return charts


def _informational_summary(state: InvestigationState, status: str) -> str:
    return _default_informational_summary(state, status)


def _default_informational_summary(state: InvestigationState, status: str) -> str:
    invoked = ", ".join(tool.value for tool in state.tools_invoked) or "none"
    skipped = ", ".join(item.tool.value for item in state.tools_skipped) or "none"
    return (
        f"Investigation {status}: invoked [{invoked}]; skipped [{skipped}]; "
        f"route={state.route.value}."
    )


def _transaction_total_minor(result: ToolResult) -> float | None:
    feature = result.data.get("feature_result")
    if not isinstance(feature, dict):
        return None
    values = feature.get("values")
    if not isinstance(values, list):
        return None
    for item in values:
        if not isinstance(item, dict):
            continue
        if str(item.get("name")) != "transaction_total":
            continue
        raw = item.get("value")
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return None


def _spend_comparison_payload(
    state: InvestigationState,
) -> tuple[str, dict[str, Any]] | None:
    current: ToolResult | None = None
    prior: ToolResult | None = None
    for result in state.tool_results:
        if result.tool is not ToolName.FEATURE_ENGINEERING:
            continue
        if result.status is not ToolStatus.SUCCESS:
            continue
        role = str(result.data.get("window_role") or "")
        if role == "current":
            current = result
        elif role == "prior":
            prior = result
    if current is None or prior is None:
        return None
    current_minor = _transaction_total_minor(current)
    prior_minor = _transaction_total_minor(prior)
    if current_minor is None or prior_minor is None:
        return None
    entity_ids = list(current.scope.customer_ids or [])
    entity_id = str(entity_ids[0]) if entity_ids else "UNKNOWN"
    delta = current_minor - prior_minor
    ratio = (current_minor / prior_minor) if prior_minor > 0 else None
    elevated = (prior_minor > 0 and ratio is not None and ratio >= 1.5) or (
        prior_minor == 0 and current_minor > 0
    )
    current_usd = current_minor / 100.0
    prior_usd = prior_minor / 100.0
    delta_usd = delta / 100.0
    ratio_text = f"{ratio:.2f}x" if ratio is not None else "n/a"
    summary = (
        f"Spend comparison for {entity_id}: current=${current_usd:,.2f} vs "
        f"prior=${prior_usd:,.2f} (Δ=${delta_usd:,.2f}, ratio={ratio_text}). "
        f"Elevated vs prior baseline: {'yes' if elevated else 'no'}."
    )
    return summary, {
        "spend_comparison": {
            "entity_id": entity_id,
            "current_minor": current_minor,
            "prior_minor": prior_minor,
            "delta_minor": delta,
            "ratio": ratio,
            "elevated": elevated,
        }
    }


def _eda_informational_payload(
    state: InvestigationState,
    charts: list[ChartSpec],
) -> tuple[str, dict[str, Any]] | None:
    cohort = _latest(state.tool_results, tool=ToolName.EDA, operation="cohort_profile")
    if cohort is None or cohort.status not in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}:
        return None
    data = dict(cohort.data)
    txn_count = data.get("transaction_count")
    cust_count = data.get("customer_count")
    summary = (
        f"EDA cohort profile: {txn_count} transactions across {cust_count} customers; "
        f"{len(charts)} chart(s)."
    )
    return summary, {
        "eda_cohort": {
            "transaction_count": txn_count,
            "customer_count": cust_count,
            "amount_min_minor": data.get("amount_min_minor"),
            "amount_max_minor": data.get("amount_max_minor"),
            "amount_mean_minor": data.get("amount_mean_minor"),
            "segment_counts": data.get("segment_counts") or {},
            "chart_ids": [chart.chart_id for chart in charts],
        }
    }


def _informational_payload(
    state: InvestigationState,
    status: str,
    charts: list[ChartSpec],
) -> tuple[str, dict[str, Any]]:
    base: dict[str, Any] = {
        "status": status,
        "tools_invoked": [tool.value for tool in state.tools_invoked],
        "tools_skipped": [
            {"tool": item.tool.value, "reason": item.reason} for item in state.tools_skipped
        ],
    }
    spend = _spend_comparison_payload(state)
    if spend is not None:
        summary, extra = spend
        base.update(extra)
        return summary, base
    eda = _eda_informational_payload(state, charts)
    if eda is not None:
        summary, extra = eda
        base.update(extra)
        return summary, base
    return _default_informational_summary(state, status), base


def _answer_text(
    state: InvestigationState,
    summary: ExecutionSummary,
    status: str,
    flagged: list[FlaggedResult],
) -> str:
    parts = [
        f"Status={status}.",
        f"Route={summary.route.value}.",
        f"Invoked={len(summary.tools_invoked)} tool(s).",
        f"Skipped={len(summary.tools_skipped)} tool(s).",
    ]
    if flagged:
        item = flagged[0]
        parts.append(
            f"Flagged {item.entity_type.value}:{item.entity_id} "
            f"{item.risk_level.value}/{item.escalation_action.value} "
            f"(score={item.risk_score:.1f})."
        )
        explanation = _latest_explanation(state.tool_results)
        if explanation:
            parts.append(str(explanation.get("summary") or ""))
    if state.warnings:
        parts.append(f"Warnings={len(state.warnings)}.")
    return " ".join(part for part in parts if part).strip()


def _latest_explanation(results: list[ToolResult]) -> dict[str, Any] | None:
    for result in reversed(results):
        if result.tool is ToolName.EXPLANATION and result.status is ToolStatus.SUCCESS:
            return dict(result.data)
    return None
