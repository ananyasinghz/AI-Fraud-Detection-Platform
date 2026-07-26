"""Investigation create/get with Phase 3 tool-result sidecar persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import AppError
from backend.app.data.models import Investigation
from backend.app.domain.api import InvestigationCreateRequest
from backend.app.domain.evidence import ToolResult
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import ToolRegistry


def _results_path(data_dir: Path, investigation_id: str) -> Path:
    return data_dir / "runtime" / "investigation_results" / f"{investigation_id}.json"


def save_tool_results(data_dir: Path, investigation_id: str, results: list[ToolResult]) -> None:
    path = _results_path(data_dir, investigation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in results]
    path.write_text(json.dumps(payload), encoding="utf-8")


def load_tool_results(data_dir: Path, investigation_id: str) -> list[ToolResult]:
    path = _results_path(data_dir, investigation_id)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ToolResult.model_validate(item) for item in raw]


def create_investigation(
    session: Session,
    request: InvestigationCreateRequest,
    *,
    context: ToolContext,
    registry: ToolRegistry,
    data_dir: Path,
) -> tuple[Investigation, list[ToolResult]]:
    request_id = request.request_id or f"req-{uuid4().hex}"
    existing = session.scalar(select(Investigation).where(Investigation.request_id == request_id))
    if existing is not None:
        return existing, load_tool_results(data_dir, existing.investigation_id)

    results = registry.execute_plan(request.plan, context=context)
    now = datetime.now(tz=UTC)
    investigation = Investigation(
        investigation_id=f"inv-{uuid4().hex}",
        request_id=request_id,
        query_text=request.query,
        route=request.route.value,
        status="completed",
        created_at=now,
        completed_at=now,
    )
    session.add(investigation)
    session.flush()
    save_tool_results(data_dir, investigation.investigation_id, results)
    return investigation, results


def get_investigation(session: Session, investigation_id: str) -> Investigation | None:
    return session.get(Investigation, investigation_id)


def require_investigation(session: Session, investigation_id: str) -> Investigation:
    investigation = get_investigation(session, investigation_id)
    if investigation is None:
        raise AppError(
            code="INVESTIGATION_NOT_FOUND",
            message="investigation not found",
            status_code=404,
        )
    return investigation
