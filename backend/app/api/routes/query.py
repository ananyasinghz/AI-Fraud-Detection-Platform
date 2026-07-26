"""Deterministic query execution with a supplied ValidatedPlan."""

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
from backend.app.domain.api import QueryRequest, QueryResponse
from backend.app.services import investigations as investigation_service
from backend.app.tools.registry import UnknownToolError, UnknownToolOperationError

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def execute_query(
    body: QueryRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    policy: PolicyDep,
    registry: RegistryDep,
) -> QueryResponse:
    context = build_tool_context(
        session=session,
        settings=settings,
        policy=policy,
        filters=body.filters,
        as_of=body.as_of,
        request=request,
    )
    request_id = getattr(request.state, "request_id", "unknown")
    try:
        outcome = investigation_service.execute_query_plan(
            session,
            request_id=request_id,
            query=body.query,
            route=body.route,
            detected_intent=body.detected_intent,
            filters=body.filters,
            plan=body.plan,
            as_of=body.as_of,
            context=context,
            registry=registry,
            settings=settings,
        )
    except (UnknownToolError, UnknownToolOperationError) as exc:
        raise AppError(code="UNKNOWN_TOOL", message=str(exc), status_code=422) from exc
    except ValueError as exc:
        raise AppError(code="INVALID_PLAN", message=str(exc), status_code=422) from exc

    return QueryResponse(
        request_id=request_id,
        tool_results=outcome.state.tool_results,
        answer=outcome.final_response.answer,
        execution_summary=outcome.final_response.execution_summary,
        status=outcome.status,  # type: ignore[arg-type]
    )
