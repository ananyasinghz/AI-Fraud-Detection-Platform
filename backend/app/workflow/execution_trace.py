"""Append-only execution trace and summary derivation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolResult
from backend.app.domain.responses import ExecutionSummary, SkippedTool
from backend.app.workflow.state import InvestigationState

StepEventKind = Literal["planned", "running", "succeeded", "failed", "skipped", "timed_out"]


@dataclass(frozen=True)
class TraceEvent:
    step_id: str
    tool: ToolName
    operation: str
    event: StepEventKind
    reason: str | None = None
    duration_ms: int | None = None
    attempt: int = 1
    tool_result: ToolResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass
class ExecutionTrace:
    """In-memory append-only step event log for one run."""

    events: list[TraceEvent] = field(default_factory=list)

    def append(self, event: TraceEvent) -> None:
        self.events.append(event)

    def terminal_events(self) -> list[TraceEvent]:
        """Latest terminal event per step_id (succeeded/failed/skipped/timed_out)."""
        latest: dict[str, TraceEvent] = {}
        for event in self.events:
            if event.event in {"succeeded", "failed", "skipped", "timed_out"}:
                latest[event.step_id] = event
        return list(latest.values())

    def build_summary(self, state: InvestigationState) -> ExecutionSummary:
        """Build ExecutionSummary from state populated exclusively by this trace."""
        del self
        return ExecutionSummary(
            query=state.query,
            detected_intent=state.detected_intent,
            route=state.route,
            filters=state.filters,
            plan=state.plan,
            tools_invoked=list(state.tools_invoked),
            tools_skipped=list(state.tools_skipped),
            fallbacks=list(state.fallbacks),
            warnings=list(state.warnings),
        )

    def to_persistence_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for event in self.events:
            rows.append(
                {
                    "step_id": event.step_id,
                    "tool": event.tool.value,
                    "operation": event.operation,
                    "event": event.event,
                    "reason": event.reason,
                    "duration_ms": event.duration_ms,
                    "attempt": event.attempt,
                    "tool_result_json": (
                        event.tool_result.model_dump(mode="json")
                        if event.tool_result is not None
                        else None
                    ),
                    "created_at": event.created_at,
                }
            )
        return rows


def record_skip(
    state: InvestigationState,
    *,
    tool: ToolName,
    reason: str,
) -> None:
    if any(item.tool is tool for item in state.tools_skipped):
        return
    if tool in state.tools_invoked:
        return
    state.tools_skipped.append(SkippedTool(tool=tool, reason=reason))


def record_invoked(state: InvestigationState, tool: ToolName) -> None:
    if tool not in state.tools_invoked:
        state.tools_invoked.append(tool)


def is_successful_status(status: ToolStatus) -> bool:
    return status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}
