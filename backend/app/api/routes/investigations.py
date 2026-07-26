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
from backend.app.domain.evidence import ToolResult
from backend.app.services import investigations as investigation_service
from backend.app.tools.registry import UnknownToolError, UnknownToolOperationError

router = APIRouter(tags=["investigations"])


def _to_response(
    investigation: Investigation,
    tool_results: list[ToolResult],
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
    context = build_tool_context(
        session=session,
        settings=settings,
        policy=policy,
        filters=body.filters,
        as_of=body.as_of,
        request=request,
    )
    try:
        investigation, results = investigation_service.create_investigation(
            session,
            body,
            context=context,
            registry=registry,
            data_dir=settings.data_dir,
        )
    except (UnknownToolError, UnknownToolOperationError) as exc:
        raise AppError(code="UNKNOWN_TOOL", message=str(exc), status_code=422) from exc
    except ValueError as exc:
        raise AppError(code="INVALID_PLAN", message=str(exc), status_code=422) from exc
    return _to_response(investigation, results)


@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(
    investigation_id: str,
    session: SessionDep,
    settings: SettingsDep,
) -> InvestigationResponse:
    investigation = investigation_service.require_investigation(session, investigation_id)
    results = investigation_service.load_tool_results(settings.data_dir, investigation_id)
    return _to_response(investigation, results)
