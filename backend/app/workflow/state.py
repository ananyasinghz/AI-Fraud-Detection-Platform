"""Mutable investigation state carried through graph execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.app.domain.enums import IntentType, RouteType, ToolName
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import ValidatedPlan
from backend.app.domain.responses import SkippedTool


@dataclass
class InvestigationState:
    """In-memory workflow state for one plan execution."""

    request_id: str
    query: str
    route: RouteType
    detected_intent: IntentType
    filters: NormalizedFilters
    plan: ValidatedPlan
    as_of: datetime
    investigation_id: str | None = None
    run_id: str | None = None
    current_step_id: str | None = None
    completed_step_ids: list[str] = field(default_factory=list)
    succeeded_step_ids: set[str] = field(default_factory=set)
    tool_results: list[ToolResult] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    tools_invoked: list[ToolName] = field(default_factory=list)
    tools_skipped: list[SkippedTool] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    required_failure: bool = False
    optional_degraded: bool = False
    # Phase 8 placeholders (unused until risk/explanation land).
    risk_placeholder: dict[str, Any] | None = None
    escalation_placeholder: dict[str, Any] | None = None
    explanation_placeholder: dict[str, Any] | None = None
