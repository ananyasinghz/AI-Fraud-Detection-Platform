"""Persist and load investigation execution traces from the database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.data.models import InvestigationRun, InvestigationStepEvent
from backend.app.domain.evidence import ToolResult
from backend.app.domain.responses import ExecutionSummary
from backend.app.workflow.graph import ExecutionOutcome
from backend.app.workflow.state import InvestigationState


def create_run(
    session: Session,
    state: InvestigationState,
) -> InvestigationRun:
    run = InvestigationRun(
        run_id=f"run-{uuid4().hex}",
        investigation_id=state.investigation_id,
        request_id=state.request_id,
        query_text=state.query,
        route=state.route.value,
        intent=state.detected_intent.value,
        plan_snapshot=state.plan.model_dump(mode="json"),
        status="running",
        started_at=datetime.now(tz=UTC),
    )
    session.add(run)
    session.flush()
    state.run_id = run.run_id
    return run


def persist_outcome(
    session: Session,
    outcome: ExecutionOutcome,
) -> InvestigationRun:
    run_id = outcome.state.run_id
    if run_id is None:
        raise ValueError("execution outcome missing run_id")
    run = session.get(InvestigationRun, run_id)
    if run is None:
        raise ValueError(f"investigation run not found: {run_id}")

    now = datetime.now(tz=UTC)
    for row in outcome.trace.to_persistence_rows():
        session.add(
            InvestigationStepEvent(
                run_id=run_id,
                step_id=row["step_id"],
                tool=row["tool"],
                operation=row["operation"],
                event=row["event"],
                reason=row["reason"],
                duration_ms=row["duration_ms"],
                attempt=row["attempt"],
                tool_result_json=row["tool_result_json"],
                created_at=row["created_at"],
            )
        )
    run.status = outcome.status
    run.completed_at = now
    run.execution_summary_json = outcome.final_response.execution_summary.model_dump(mode="json")
    run.final_answer = outcome.final_response.answer
    session.flush()
    return run


def load_latest_run(
    session: Session,
    *,
    investigation_id: str,
) -> InvestigationRun | None:
    statement = (
        select(InvestigationRun)
        .where(InvestigationRun.investigation_id == investigation_id)
        .order_by(InvestigationRun.started_at.desc())
        .limit(1)
    )
    return session.scalar(statement)


def load_tool_results_for_run(session: Session, run_id: str) -> list[ToolResult]:
    statement = (
        select(InvestigationStepEvent)
        .where(InvestigationStepEvent.run_id == run_id)
        .where(InvestigationStepEvent.event.in_(("succeeded", "failed", "skipped", "timed_out")))
        .order_by(InvestigationStepEvent.created_at.asc(), InvestigationStepEvent.event_id.asc())
    )
    results: list[ToolResult] = []
    seen_steps: set[str] = set()
    # Prefer latest terminal event per step_id.
    events = list(session.scalars(statement))
    latest: dict[str, InvestigationStepEvent] = {}
    for event in events:
        latest[event.step_id] = event
    for step_id in sorted(latest):
        event = latest[step_id]
        if event.tool_result_json is None:
            continue
        if step_id in seen_steps:
            continue
        seen_steps.add(step_id)
        results.append(ToolResult.model_validate(event.tool_result_json))
    return results


def load_execution_summary(run: InvestigationRun) -> ExecutionSummary | None:
    if run.execution_summary_json is None:
        return None
    return ExecutionSummary.model_validate(run.execution_summary_json)


def load_trace_events(session: Session, run_id: str) -> list[InvestigationStepEvent]:
    statement = (
        select(InvestigationStepEvent)
        .where(InvestigationStepEvent.run_id == run_id)
        .order_by(InvestigationStepEvent.created_at.asc(), InvestigationStepEvent.event_id.asc())
    )
    return list(session.scalars(statement))
