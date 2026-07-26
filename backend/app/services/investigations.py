"""Investigation create/get with DB-backed execution traces."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.data.models import Investigation
from backend.app.domain.api import InvestigationCreateRequest
from backend.app.domain.enums import IntentType, RouteType, ToolName
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.domain.responses import ExecutionSummary, FinalResponse
from backend.app.services import trace_store
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import ToolRegistry
from backend.app.workflow.execution_trace import ExecutionTrace
from backend.app.workflow.graph import ExecutionOutcome, GraphExecutor
from backend.app.workflow.intent import intent_from_route
from backend.app.workflow.state import InvestigationState


def _sidecar_path(data_dir: Path, investigation_id: str) -> Path:
    return data_dir / "runtime" / "investigation_results" / f"{investigation_id}.json"


def _load_sidecar(data_dir: Path, investigation_id: str) -> list[ToolResult]:
    path = _sidecar_path(data_dir, investigation_id)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [ToolResult.model_validate(item) for item in raw]


def _placeholder_plan() -> ValidatedPlan:
    return ValidatedPlan(
        strategy="restored",
        planner_version="restored.v1",
        steps=[
            PlanStep(
                step_id="restored",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "unknown"},
                reason="restored investigation payload",
            )
        ],
    )


def create_investigation(
    session: Session,
    request: InvestigationCreateRequest,
    *,
    context: ToolContext,
    registry: ToolRegistry,
    settings: Settings,
) -> tuple[Investigation, ExecutionOutcome]:
    from backend.app.services.routing import resolve_for_execution

    request_id = request.request_id or f"req-{uuid4().hex}"
    existing = session.scalar(select(Investigation).where(Investigation.request_id == request_id))
    if existing is not None:
        return existing, outcome_from_stored(session, existing, settings.data_dir)

    resolved = resolve_for_execution(
        query=request.query,
        as_of=request.as_of,
        filters=request.filters,
        plan=request.plan,
        route=request.route,
        detected_intent=request.detected_intent,
        settings=settings,
    )
    # Keep request-scoped tool context filters aligned with routed filters.
    context.filters = resolved.filters

    now = datetime.now(tz=UTC)
    investigation = Investigation(
        investigation_id=f"inv-{uuid4().hex}",
        request_id=request_id,
        query_text=request.query,
        route=resolved.route.value,
        status="running",
        created_at=now,
        completed_at=None,
    )
    session.add(investigation)
    session.flush()

    state = InvestigationState(
        request_id=request_id,
        query=resolved.query,
        route=resolved.route,
        detected_intent=resolved.detected_intent,
        filters=resolved.filters,
        plan=resolved.plan,
        as_of=request.as_of,
        investigation_id=investigation.investigation_id,
    )
    trace_store.create_run(session, state)
    outcome = GraphExecutor(registry=registry, settings=settings).execute(
        state,
        context=context,
    )
    trace_store.persist_outcome(session, outcome)
    investigation.status = outcome.status
    investigation.completed_at = datetime.now(tz=UTC)
    session.flush()
    return investigation, outcome


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


def load_investigation_payload(
    session: Session,
    investigation: Investigation,
    *,
    data_dir: Path,
) -> tuple[list[ToolResult], ExecutionSummary | None, str | None]:
    run = trace_store.load_latest_run(session, investigation_id=investigation.investigation_id)
    if run is not None:
        results = trace_store.load_tool_results_for_run(session, run.run_id)
        summary = trace_store.load_execution_summary(run)
        return results, summary, run.final_answer
    return _load_sidecar(data_dir, investigation.investigation_id), None, None


def outcome_from_stored(
    session: Session,
    investigation: Investigation,
    data_dir: Path,
) -> ExecutionOutcome:
    results, summary, answer = load_investigation_payload(
        session,
        investigation,
        data_dir=data_dir,
    )
    if summary is None:
        summary = ExecutionSummary(
            query=investigation.query_text,
            detected_intent=IntentType.ENTITY_INVESTIGATION,
            route=RouteType(investigation.route),
            filters=NormalizedFilters(),
            plan=_placeholder_plan(),
            tools_invoked=[],
            tools_skipped=[],
        )
    plan = summary.plan or _placeholder_plan()
    state = InvestigationState(
        request_id=investigation.request_id,
        query=investigation.query_text,
        route=summary.route,
        detected_intent=summary.detected_intent,
        filters=summary.filters,
        plan=plan,
        as_of=investigation.created_at,
        investigation_id=investigation.investigation_id,
        tool_results=results,
        tools_invoked=list(summary.tools_invoked),
        tools_skipped=list(summary.tools_skipped),
        warnings=list(summary.warnings),
        fallbacks=list(summary.fallbacks),
    )
    final = FinalResponse(
        request_id=investigation.request_id,
        generated_at=datetime.now(tz=UTC),
        execution_summary=summary,
        supporting_evidence=results,
        answer=answer or "Restored investigation result.",
    )
    return ExecutionOutcome(
        state=state,
        trace=ExecutionTrace(),
        final_response=final,
        status=investigation.status,
    )


def execute_query_plan(
    session: Session,
    *,
    request_id: str,
    query: str,
    route: RouteType,
    detected_intent: IntentType | None,
    filters: NormalizedFilters,
    plan: ValidatedPlan,
    as_of: datetime,
    context: ToolContext,
    registry: ToolRegistry,
    settings: Settings,
) -> ExecutionOutcome:
    intent = detected_intent or intent_from_route(route)
    state = InvestigationState(
        request_id=request_id,
        query=query,
        route=route,
        detected_intent=intent,
        filters=filters,
        plan=plan,
        as_of=as_of,
        investigation_id=None,
    )
    trace_store.create_run(session, state)
    outcome = GraphExecutor(registry=registry, settings=settings).execute(
        state,
        context=context,
    )
    trace_store.persist_outcome(session, outcome)
    return outcome
