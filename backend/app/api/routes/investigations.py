"""Investigation create and retrieve endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.api.dependencies import (
    PolicyDep,
    RegistryDep,
    SessionDep,
    SettingsDep,
    build_tool_context,
)
from backend.app.core.errors import AppError
from backend.app.data.models import Investigation
from backend.app.domain.api import InvestigationCreateRequest, InvestigationResponse
from backend.app.domain.charts import ChartSpec
from backend.app.domain.evidence import ToolResult
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.responses import ExecutionSummary, ResultItem
from backend.app.services import investigations as investigation_service
from backend.app.services.routing import resolve_for_execution
from backend.app.tools.registry import UnknownToolError, UnknownToolOperationError
from backend.app.workflow.execution_trace import ExecutionTrace
from backend.app.workflow.nodes.aggregate import build_final_response

router = APIRouter(tags=["investigations"])


def _to_response(
    investigation: Investigation,
    *,
    tool_results: list[ToolResult],
    execution_summary: ExecutionSummary | None,
    answer: str | None,
    parsed_intent: ParsedIntent | None = None,
    clarification: str | None = None,
    needs_planner: bool = False,
    results: list[ResultItem] | None = None,
    charts: list[ChartSpec] | None = None,
    supporting_evidence: list[ToolResult] | None = None,
) -> InvestigationResponse:
    return InvestigationResponse(
        investigation_id=investigation.investigation_id,
        request_id=investigation.request_id,
        query_text=investigation.query_text,
        route=investigation.route,
        status=investigation.status,
        created_at=investigation.created_at,
        completed_at=investigation.completed_at,
        tool_results=tool_results,
        execution_summary=execution_summary,
        answer=answer,
        parsed_intent=parsed_intent,
        clarification=clarification,
        needs_planner=needs_planner,
        results=list(results or []),
        charts=list(charts or []),
        supporting_evidence=list(supporting_evidence or tool_results),
    )


@router.post("/investigations", response_model=InvestigationResponse)
async def create_investigation(
    body: InvestigationCreateRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    policy: PolicyDep,
    registry: RegistryDep,
) -> InvestigationResponse:
    resolved = resolve_for_execution(
        query=body.query,
        as_of=body.as_of,
        filters=body.filters,
        plan=body.plan,
        route=body.route,
        detected_intent=body.detected_intent,
        settings=settings,
    )
    # Rebuild body-equivalent with resolved plan for the service.
    resolved_body = body.model_copy(
        update={
            "plan": resolved.plan,
            "route": resolved.route,
            "filters": resolved.filters,
            "detected_intent": resolved.detected_intent,
        }
    )
    request_id = getattr(request.state, "request_id", "unknown")
    context = build_tool_context(
        session=session,
        settings=settings,
        policy=policy,
        filters=resolved.filters,
        as_of=body.as_of,
        request=request,
        request_id=request_id,
    )
    try:
        investigation, outcome = investigation_service.create_investigation(
            session,
            resolved_body,
            context=context,
            registry=registry,
            settings=settings,
        )
    except (UnknownToolError, UnknownToolOperationError) as exc:
        raise AppError(code="UNKNOWN_TOOL", message=str(exc), status_code=422) from exc
    except ValueError as exc:
        raise AppError(code="INVALID_PLAN", message=str(exc), status_code=422) from exc
    final = outcome.final_response
    return _to_response(
        investigation,
        tool_results=outcome.state.tool_results,
        execution_summary=final.execution_summary,
        answer=final.answer,
        parsed_intent=resolved.parsed_intent,
        clarification=resolved.clarification,
        needs_planner=resolved.needs_planner,
        results=list(final.results),
        charts=list(final.charts),
        supporting_evidence=list(final.supporting_evidence),
    )


@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(
    investigation_id: str,
    session: SessionDep,
    settings: SettingsDep,
) -> InvestigationResponse:
    investigation = investigation_service.require_investigation(session, investigation_id)
    outcome = investigation_service.outcome_from_stored(
        session,
        investigation,
        settings.data_dir,
    )
    # Rebuild FlaggedResult/charts from stored tool envelopes via aggregate.
    rebuilt = build_final_response(
        outcome.state,
        ExecutionTrace(),
        status=investigation.status,
    )
    return _to_response(
        investigation,
        tool_results=outcome.state.tool_results,
        execution_summary=outcome.final_response.execution_summary,
        answer=outcome.final_response.answer,
        results=list(rebuilt.results),
        charts=list(rebuilt.charts),
        supporting_evidence=list(rebuilt.supporting_evidence),
    )
