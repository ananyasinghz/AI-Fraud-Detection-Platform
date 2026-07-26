"""Aggregate node: build FinalResponse from execution state (informational only)."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.app.domain.charts import ChartSpec
from backend.app.domain.evidence import ToolResult
from backend.app.domain.responses import (
    ExecutionSummary,
    FinalResponse,
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
    results: list[ResultItem] = [
        InformationalResult(
            summary=_informational_summary(state, status),
            data={
                "status": status,
                "tools_invoked": [tool.value for tool in state.tools_invoked],
                "tools_skipped": [
                    {"tool": item.tool.value, "reason": item.reason} for item in state.tools_skipped
                ],
            },
            evidence_refs=list(state.evidence_refs),
        )
    ]
    answer = _answer_text(state, summary, status)
    return FinalResponse(
        request_id=state.request_id,
        generated_at=datetime.now(tz=UTC),
        execution_summary=summary,
        results=results,
        supporting_evidence=list(state.tool_results),
        charts=charts,
        answer=answer,
    )


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
) -> str:
    parts = [
        f"Status={status}.",
        f"Route={summary.route.value}.",
        f"Invoked={len(summary.tools_invoked)} tool(s).",
        f"Skipped={len(summary.tools_skipped)} tool(s).",
    ]
    if state.warnings:
        parts.append(f"Warnings={len(state.warnings)}.")
    return " ".join(parts)
