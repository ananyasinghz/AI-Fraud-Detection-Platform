"""Map ToolName to registry dispatch (and Phase 7/8 skip stubs)."""

from __future__ import annotations

from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolError, ToolProvenance, ToolResult
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result
from backend.app.tools.registry import (
    ToolRegistry,
    UnknownToolError,
    UnknownToolOperationError,
)
from backend.app.tools.stubs import handle_explanation, handle_risk_classification

PHASE_7_TOOLS = frozenset({ToolName.GRAPH_ANALYSIS, ToolName.RETRIEVAL})
PHASE_8_TOOLS = frozenset(
    {
        ToolName.RISK_CLASSIFICATION,
        ToolName.EXPLANATION,
        ToolName.VERIFICATION,
        ToolName.ESCALATION,
    }
)

NODE_BY_TOOL: dict[ToolName, str] = {
    ToolName.SQL_LOOKUP: "sql_node",
    ToolName.EDA: "eda_node",
    ToolName.FEATURE_ENGINEERING: "feature_engineering_node",
    ToolName.ANOMALY_DETECTION: "anomaly_detection_node",
    ToolName.GRAPH_ANALYSIS: "graph_analysis_node",
    ToolName.RETRIEVAL: "retrieval_node",
    ToolName.RISK_CLASSIFICATION: "risk_node",
    ToolName.EXPLANATION: "explanation_node",
    ToolName.VERIFICATION: "evidence_verification_node",
    ToolName.ESCALATION: "escalation_node",
}


def _skipped_stub(
    tool: ToolName,
    operation: str,
    context: ToolContext,
    reason: str,
) -> ToolResult:
    timer = Timer()
    return make_result(
        tool=tool,
        operation=operation,
        status=ToolStatus.SKIPPED,
        scope=context.filters,
        warnings=[reason],
        duration_ms=timer.ms(),
        provenance=ToolProvenance(
            source=NODE_BY_TOOL.get(tool, tool.value),
            query_or_version="workflow.stub.v1",
            policy_version=context.policy.version,
        ),
    )


def run_tool_node(
    *,
    tool: ToolName,
    operation: str,
    parameters: dict[str, Any],
    context: ToolContext,
    registry: ToolRegistry,
) -> ToolResult:
    """Invoke one plan step through the registry or a structured skip stub."""
    if tool in PHASE_7_TOOLS:
        return _skipped_stub(tool, operation, context, "PHASE_7_NOT_IMPLEMENTED")
    if tool is ToolName.VERIFICATION or tool is ToolName.ESCALATION:
        return _skipped_stub(tool, operation, context, "PHASE_8_NOT_IMPLEMENTED")
    if tool is ToolName.RISK_CLASSIFICATION:
        return handle_risk_classification(context, operation, parameters)
    if tool is ToolName.EXPLANATION:
        return handle_explanation(context, operation, parameters)
    try:
        return registry.dispatch(
            tool,
            operation,
            context=context,
            parameters=parameters,
        )
    except UnknownToolError:
        return _skipped_stub(tool, operation, context, "UNKNOWN_TOOL")
    except UnknownToolOperationError as exc:
        timer = Timer()
        return make_result(
            tool=tool,
            operation=operation,
            status=ToolStatus.FAILED,
            scope=context.filters,
            duration_ms=timer.ms(),
            provenance=ToolProvenance(
                source=NODE_BY_TOOL.get(tool, tool.value),
                query_or_version="workflow.v1",
                policy_version=context.policy.version,
            ),
            error=ToolError(
                code="UNKNOWN_OPERATION",
                message=str(exc),
                retryable=False,
            ),
        )
