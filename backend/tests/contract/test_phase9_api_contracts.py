"""Phase 9 contract tests for enriched query/customer list responses."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.app.domain.api import CustomerListResponse, CustomerResponse, QueryResponse
from backend.app.domain.enums import (
    EntityType,
    EscalationAction,
    IntentType,
    RiskLevel,
    RouteType,
    ToolName,
)
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.responses import (
    ExecutionSummary,
    FlaggedResult,
    InformationalResult,
)


def test_query_response_accepts_final_response_fields() -> None:
    summary = ExecutionSummary(
        query="Show me transactions over $10,000",
        detected_intent=IntentType.SIMPLE_LOOKUP,
        route=RouteType.SIMPLE_LOOKUP,
        filters=NormalizedFilters(),
        tools_invoked=[ToolName.SQL_LOOKUP],
        tools_skipped=[],
    )
    payload = QueryResponse(
        request_id="req-1",
        tool_results=[],
        answer="Status=completed.",
        execution_summary=summary,
        status="completed",
        results=[
            InformationalResult(summary="ok", data={"n": 1}, evidence_refs=[]),
            FlaggedResult(
                entity_type=EntityType.CUSTOMER,
                entity_id="C1",
                risk_score=55,
                risk_level=RiskLevel.MEDIUM,
                confidence=0.8,
                reasons=["rule fired"],
                escalation_action=EscalationAction.REVIEW,
                evidence_refs=["ev-1"],
            ),
        ],
        charts=[],
        supporting_evidence=[],
        parsed_intent=ParsedIntent(
            intent=IntentType.SIMPLE_LOOKUP,
            target_scope=__import__(
                "backend.app.domain.enums", fromlist=["TargetScope"]
            ).TargetScope.DATASET,
            filters=NormalizedFilters(),
            confidence=0.9,
            parser_version="t",
        ),
    )
    assert len(payload.results) == 2
    assert payload.results[1].result_type == "flagged"


def test_customer_list_response_contract() -> None:
    as_of = datetime(2026, 2, 15, tzinfo=UTC)
    body = CustomerListResponse(
        items=[CustomerResponse(customer_id="C1", created_at=as_of, status="active")],
        total=1,
        limit=50,
        offset=0,
    )
    assert body.total == 1
    assert body.items[0].customer_id == "C1"
