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
        results.append(
            InformationalResult(
                summary=_informational_summary(state, status),
                data={
                    "status": status,
                    "tools_invoked": [tool.value for tool in state.tools_invoked],
                    "tools_skipped": [
                        {"tool": item.tool.value, "reason": item.reason}
                        for item in state.tools_skipped
                    ],
                },
                evidence_refs=list(state.evidence_refs),
            )
        )
    elif status != "completed":
        results.insert(
            0,
            InformationalResult(
                summary=_informational_summary(state, status),
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
    invoked = ", ".join(tool.value for tool in state.tools_invoked) or "none"
    skipped = ", ".join(item.tool.value for item in state.tools_skipped) or "none"
    return (
        f"Investigation {status}: invoked [{invoked}]; skipped [{skipped}]; "
        f"route={state.route.value}."
    )


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
