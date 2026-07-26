"""Phase 8 tool stubs registered in Phase 3 for interface completeness."""

from __future__ import annotations

from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result


def handle_risk_classification(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> ToolResult:
    del parameters
    timer = Timer()
    return make_result(
        tool=ToolName.RISK_CLASSIFICATION,
        operation=operation,
        status=ToolStatus.SKIPPED,
        scope=context.filters,
        warnings=["PHASE_8_NOT_IMPLEMENTED"],
        duration_ms=timer.ms(),
        provenance=ToolProvenance(
            source="risk_classification",
            query_or_version="stub.v1",
            policy_version=context.policy.version,
        ),
    )


def handle_explanation(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> ToolResult:
    del parameters
    timer = Timer()
    return make_result(
        tool=ToolName.EXPLANATION,
        operation=operation,
        status=ToolStatus.SKIPPED,
        scope=context.filters,
        warnings=["PHASE_8_NOT_IMPLEMENTED"],
        duration_ms=timer.ms(),
        provenance=ToolProvenance(
            source="explanation",
            query_or_version="stub.v1",
            policy_version=context.policy.version,
        ),
    )
