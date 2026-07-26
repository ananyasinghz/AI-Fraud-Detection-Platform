"""Dependency-ordered graph executor with timeout, retry, and skip policy."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass

from backend.app.core.config import Settings
from backend.app.domain.enums import ToolStatus
from backend.app.domain.evidence import ToolError, ToolProvenance, ToolResult
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.domain.responses import FinalResponse
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import make_result
from backend.app.tools.registry import ToolRegistry
from backend.app.workflow.execution_trace import (
    ExecutionTrace,
    TraceEvent,
    is_successful_status,
    record_invoked,
    record_skip,
)
from backend.app.workflow.nodes.adapters import NODE_BY_TOOL, run_tool_node
from backend.app.workflow.nodes.aggregate import build_final_response
from backend.app.workflow.state import InvestigationState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionOutcome:
    state: InvestigationState
    trace: ExecutionTrace
    final_response: FinalResponse
    status: str


class GraphExecutor:
    """Execute a ValidatedPlan through tool nodes with conditional skips."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        settings: Settings,
    ) -> None:
        self._registry = registry
        self._timeout = settings.node_timeout_seconds
        self._max_retries = settings.node_max_retries

    def execute(
        self,
        state: InvestigationState,
        *,
        context: ToolContext,
    ) -> ExecutionOutcome:
        trace = ExecutionTrace()
        for step in state.plan.steps:
            trace.append(
                TraceEvent(
                    step_id=step.step_id,
                    tool=step.tool,
                    operation=step.operation,
                    event="planned",
                )
            )

        pending = {step.step_id: step for step in state.plan.steps}
        completed: set[str] = set()
        dispatched: set[str] = set()

        while pending:
            ready = [step for step in pending.values() if set(step.depends_on).issubset(completed)]
            if not ready:
                raise ValueError("plan has unresolved dependencies")
            ready.sort(key=lambda item: item.step_id)
            for step in ready:
                if step.step_id in dispatched:
                    raise RuntimeError(f"step already dispatched: {step.step_id}")
                dispatched.add(step.step_id)
                self._run_step(state, trace, step, context=context)
                completed.add(step.step_id)
                state.completed_step_ids.append(step.step_id)
                del pending[step.step_id]

        status = self._terminal_status(state)
        final = build_final_response(state, trace, status=status)
        return ExecutionOutcome(
            state=state,
            trace=trace,
            final_response=final,
            status=status,
        )

    def _run_step(
        self,
        state: InvestigationState,
        trace: ExecutionTrace,
        step: PlanStep,
        *,
        context: ToolContext,
    ) -> None:
        state.current_step_id = step.step_id
        # Phase 8 tools read prior successful/partial tool envelopes from context.
        context.prior_results = list(state.tool_results)
        context.request_id = state.request_id
        context.investigation_id = state.investigation_id
        logger.info(
            "workflow step start",
            extra={
                "request_id": state.request_id,
                "investigation_id": state.investigation_id,
                "step_id": step.step_id,
                "tool": step.tool.value,
                "node": NODE_BY_TOOL.get(step.tool, step.tool.value),
            },
        )

        unmet = [dep for dep in step.depends_on if dep not in state.succeeded_step_ids]
        if unmet:
            reason = self._dependency_reason(state, unmet)
            result = self._skipped_result(step, context, reason)
            self._record_terminal(
                state,
                trace,
                step,
                event="skipped",
                result=result,
                reason=reason,
                attempt=1,
            )
            record_skip(state, tool=step.tool, reason=reason)
            return

        attempt = 1
        while True:
            trace.append(
                TraceEvent(
                    step_id=step.step_id,
                    tool=step.tool,
                    operation=step.operation,
                    event="running",
                    attempt=attempt,
                )
            )
            result, timed_out = self._dispatch_with_timeout(
                step,
                context=context,
                attempt=attempt,
            )
            if timed_out:
                self._record_terminal(
                    state,
                    trace,
                    step,
                    event="timed_out",
                    result=result,
                    reason="NODE_TIMEOUT",
                    attempt=attempt,
                )
                self._apply_failure(state, step, result, reason="NODE_TIMEOUT")
                return

            if is_successful_status(result.status) or result.status is ToolStatus.SKIPPED:
                event = "succeeded" if is_successful_status(result.status) else "skipped"
                # Tool-internal skips still count as an invocation attempt for trace,
                # but ExecutionSummary treats SKIPPED tools as skipped not invoked.
                self._record_terminal(
                    state,
                    trace,
                    step,
                    event=event if event == "succeeded" else "skipped",
                    result=result,
                    reason=(result.warnings[0] if result.warnings else None),
                    attempt=attempt,
                )
                if is_successful_status(result.status):
                    state.succeeded_step_ids.add(step.step_id)
                    record_invoked(state, step.tool)
                    state.tool_results.append(result)
                    state.warnings.extend(result.warnings)
                    for evidence in result.evidence:
                        state.evidence_refs.append(evidence.evidence_id)
                else:
                    record_skip(
                        state,
                        tool=step.tool,
                        reason=result.warnings[0] if result.warnings else "SKIPPED",
                    )
                    state.tool_results.append(result)
                    state.warnings.extend(result.warnings)
                    if step.required:
                        state.required_failure = True
                        state.fallbacks.append(f"{step.step_id}:required_skipped")
                    else:
                        state.optional_degraded = True
                return

            # FAILED
            retryable = bool(result.error and result.error.retryable)
            if retryable and attempt <= self._max_retries:
                attempt += 1
                state.fallbacks.append(f"{step.step_id}:retry_{attempt}")
                continue
            self._record_terminal(
                state,
                trace,
                step,
                event="failed",
                result=result,
                reason=result.error.message if result.error else "TOOL_FAILED",
                attempt=attempt,
            )
            self._apply_failure(state, step, result, reason="TOOL_FAILED")
            return

    def _dispatch_with_timeout(
        self,
        step: PlanStep,
        *,
        context: ToolContext,
        attempt: int,
    ) -> tuple[ToolResult, bool]:
        del attempt
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                run_tool_node,
                tool=step.tool,
                operation=step.operation,
                parameters=dict(step.parameters),
                context=context,
                registry=self._registry,
            )
            try:
                return future.result(timeout=self._timeout), False
            except FuturesTimeoutError:
                future.cancel()
                result = make_result(
                    tool=step.tool,
                    operation=step.operation,
                    status=ToolStatus.FAILED,
                    scope=context.filters,
                    duration_ms=int(self._timeout * 1000),
                    provenance=ToolProvenance(
                        source=NODE_BY_TOOL.get(step.tool, step.tool.value),
                        query_or_version="workflow.v1",
                        policy_version=context.policy.version,
                    ),
                    error=ToolError(
                        code="NODE_TIMEOUT",
                        message=f"node exceeded {self._timeout}s",
                        retryable=True,
                    ),
                    warnings=["NODE_TIMEOUT"],
                )
                return result, True
            except Exception as exc:
                result = make_result(
                    tool=step.tool,
                    operation=step.operation,
                    status=ToolStatus.FAILED,
                    scope=context.filters,
                    duration_ms=0,
                    provenance=ToolProvenance(
                        source=NODE_BY_TOOL.get(step.tool, step.tool.value),
                        query_or_version="workflow.v1",
                        policy_version=context.policy.version,
                    ),
                    error=ToolError(
                        code="NODE_EXCEPTION",
                        message=str(exc)[:500],
                        retryable=False,
                    ),
                )
                return result, False

    def _apply_failure(
        self,
        state: InvestigationState,
        step: PlanStep,
        result: ToolResult,
        *,
        reason: str,
    ) -> None:
        state.tool_results.append(result)
        state.errors.append(f"{step.step_id}:{reason}")
        state.warnings.extend(result.warnings)
        record_skip(state, tool=step.tool, reason=reason)
        if step.required:
            state.required_failure = True
        else:
            state.optional_degraded = True
            state.fallbacks.append(f"{step.step_id}:optional_failed")

    def _record_terminal(
        self,
        state: InvestigationState,
        trace: ExecutionTrace,
        step: PlanStep,
        *,
        event: str,
        result: ToolResult,
        reason: str | None,
        attempt: int,
    ) -> None:
        del state
        trace.append(
            TraceEvent(
                step_id=step.step_id,
                tool=step.tool,
                operation=step.operation,
                event=event,  # type: ignore[arg-type]
                reason=reason,
                duration_ms=result.duration_ms,
                attempt=attempt,
                tool_result=result,
            )
        )
        logger.info(
            "workflow step %s",
            event,
            extra={
                "step_id": step.step_id,
                "tool": step.tool.value,
                "reason": reason,
            },
        )

    def _dependency_reason(self, state: InvestigationState, unmet: list[str]) -> str:
        for step_id in unmet:
            if any(item.startswith(f"{step_id}:") for item in state.errors):
                return "DEPENDENCY_FAILED"
        return "DEPENDENCY_SKIPPED"

    def _skipped_result(
        self,
        step: PlanStep,
        context: ToolContext,
        reason: str,
    ) -> ToolResult:
        return make_result(
            tool=step.tool,
            operation=step.operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=[reason],
            duration_ms=0,
            provenance=ToolProvenance(
                source=NODE_BY_TOOL.get(step.tool, step.tool.value),
                query_or_version="workflow.v1",
                policy_version=context.policy.version,
            ),
        )

    @staticmethod
    def _terminal_status(state: InvestigationState) -> str:
        # Required-tool failure/skip yields a clearly marked partial response (roadmap).
        if state.required_failure or state.optional_degraded:
            return "partial"
        if state.errors and not state.succeeded_step_ids:
            return "failed"
        return "completed"


def execute_validated_plan(
    plan: ValidatedPlan,
    *,
    state: InvestigationState,
    context: ToolContext,
    registry: ToolRegistry,
    settings: Settings,
) -> ExecutionOutcome:
    del plan  # plan is already on state
    return GraphExecutor(registry=registry, settings=settings).execute(
        state,
        context=context,
    )
