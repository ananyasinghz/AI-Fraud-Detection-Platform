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
    try:
        results = registry.execute_plan(body.plan, context=context)
    except (UnknownToolError, UnknownToolOperationError) as exc:
        raise AppError(code="UNKNOWN_TOOL", message=str(exc), status_code=422) from exc
    except ValueError as exc:
        raise AppError(code="INVALID_PLAN", message=str(exc), status_code=422) from exc

    tools = ", ".join(f"{item.tool.value}:{item.operation}" for item in results)
    return QueryResponse(
        request_id=getattr(request.state, "request_id", "unknown"),
        tool_results=results,
        answer=f"Executed {len(results)} tool step(s): {tools}",
    )
