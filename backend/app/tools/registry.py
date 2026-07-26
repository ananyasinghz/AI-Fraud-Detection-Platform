"""Named tool registry with common ToolResult envelope dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.domain.enums import ToolName
from backend.app.domain.evidence import ToolResult
from backend.app.domain.plan import ValidatedPlan
from backend.app.tools.anomaly.facade import handle_anomaly_detection
from backend.app.tools.context import ToolContext
from backend.app.tools.eda.profiling import handle_eda
from backend.app.tools.features.tool import handle_feature_engineering
from backend.app.tools.sql.lookup import handle_sql_lookup
from backend.app.tools.stubs import handle_explanation, handle_risk_classification

ToolHandler = Callable[[ToolContext, str, dict[str, Any]], ToolResult]


class UnknownToolError(LookupError):
    """Raised when a tool name is not registered."""


class UnknownToolOperationError(LookupError):
    """Raised when a tool operation is not registered."""


class ToolRegistry:
    """Dispatch allow-listed tool operations against an explicit context."""

    def __init__(self) -> None:
        self._handlers: dict[ToolName, ToolHandler] = {}
        self._operations: dict[ToolName, frozenset[str]] = {}

    def register(
        self,
        tool: ToolName,
        handler: ToolHandler,
        operations: frozenset[str],
    ) -> None:
        if tool in self._handlers:
            raise ValueError(f"tool already registered: {tool.value}")
        self._handlers[tool] = handler
        self._operations[tool] = operations

    def registered_tools(self) -> tuple[str, ...]:
        return tuple(sorted(tool.value for tool in self._handlers))

    def dispatch(
        self,
        tool: ToolName,
        operation: str,
        *,
        context: ToolContext,
        parameters: dict[str, Any] | None = None,
    ) -> ToolResult:
        handler = self._handlers.get(tool)
        if handler is None:
            raise UnknownToolError(f"unknown tool: {tool.value}")
        allowed = self._operations.get(tool, frozenset())
        if operation not in allowed:
            raise UnknownToolOperationError(
                f"unknown operation '{operation}' for tool {tool.value}"
            )
        return handler(context, operation, parameters or {})

    def execute_plan(self, plan: ValidatedPlan, *, context: ToolContext) -> list[ToolResult]:
        """Execute plan steps in dependency-respecting order."""
        pending = {step.step_id: step for step in plan.steps}
        completed: set[str] = set()
        results: list[ToolResult] = []
        while pending:
            ready = [step for step in pending.values() if set(step.depends_on).issubset(completed)]
            if not ready:
                raise ValueError("plan has unresolved dependencies")
            ready.sort(key=lambda item: item.step_id)
            for step in ready:
                result = self.dispatch(
                    step.tool,
                    step.operation,
                    context=context,
                    parameters=dict(step.parameters),
                )
                results.append(result)
                completed.add(step.step_id)
                del pending[step.step_id]
        return results


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolName.SQL_LOOKUP,
        handle_sql_lookup,
        frozenset({"get_customer", "get_transaction", "list_transactions"}),
    )
    registry.register(
        ToolName.FEATURE_ENGINEERING,
        handle_feature_engineering,
        frozenset({"compute_feature", "run_operation"}),
    )
    registry.register(
        ToolName.EDA,
        handle_eda,
        frozenset(
            {
                "cohort_profile",
                "volume_over_time",
                "missingness_quality",
                "amount_distribution",
                "class_balance",
            }
        ),
    )
    registry.register(
        ToolName.ANOMALY_DETECTION,
        handle_anomaly_detection,
        frozenset({"detect"}),
    )
    registry.register(
        ToolName.RISK_CLASSIFICATION,
        handle_risk_classification,
        frozenset({"classify"}),
    )
    registry.register(
        ToolName.EXPLANATION,
        handle_explanation,
        frozenset({"explain"}),
    )
    return registry


TOOL_REGISTRY = build_tool_registry()
