"""Contract-v1 positive and negative tests."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.domain import (
    AnalysisRequest,
    ChartSpec,
    ChartType,
    EntityType,
    EscalationAction,
    EvidenceReference,
    ExecutionSummary,
    FinalResponse,
    FlaggedResult,
    InformationalResult,
    IntentType,
    NormalizedFilters,
    ParsedIntent,
    PlanStep,
    RiskLevel,
    RouteType,
    SkippedTool,
    TargetScope,
    ToolError,
    ToolName,
    ToolProvenance,
    ToolResult,
    ToolStatus,
    ValidatedPlan,
)

NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def make_filters() -> NormalizedFilters:
    return NormalizedFilters(
        date_from=NOW - timedelta(days=30),
        date_to=NOW,
        customer_ids=["C123"],
        country="IN",
        currency="USD",
        amount_min=Decimal("10.00"),
        amount_max=Decimal("10000.00"),
    )


def make_plan() -> ValidatedPlan:
    return ValidatedPlan(
        strategy="targeted_pattern_search",
        planner_version="template.v1",
        steps=[
            PlanStep(
                step_id="features",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="structuring_features",
                parameters={"window_days": 30},
                reason="Compute required features",
            ),
            PlanStep(
                step_id="rules",
                tool=ToolName.ANOMALY_DETECTION,
                operation="rules_only",
                depends_on=["features"],
                reason="Apply relevant rules",
            ),
        ],
    )


def make_tool_result() -> ToolResult:
    return ToolResult(
        tool=ToolName.FEATURE_ENGINEERING,
        operation="structuring_features",
        status=ToolStatus.SUCCESS,
        scope=make_filters(),
        data={"rolling_count": 12},
        evidence=[
            EvidenceReference(
                evidence_id="ev.features.1",
                tool=ToolName.FEATURE_ENGINEERING,
                kind="feature",
                json_path="$.rolling_count",
                label="Rolling transaction count",
            )
        ],
        duration_ms=12,
        produced_at=NOW,
        provenance=ToolProvenance(
            source="fixture",
            query_or_version="feature-contract-v1",
        ),
    )


def test_contract_example_round_trip() -> None:
    filters = make_filters()
    request = AnalysisRequest(
        query="Find structuring patterns in the last 30 days",
        as_of=NOW,
        filters=filters,
    )
    intent = ParsedIntent(
        intent=IntentType.PATTERN_SEARCH,
        target_scope=TargetScope.CUSTOMER,
        filters=filters,
        confidence=0.98,
        extracted_entities={"customer_ids": ["C123"]},
        parser_version="fixture.v1",
    )
    plan = make_plan()

    assert request.filters.date_from == NOW - timedelta(days=30)
    assert intent.confidence == 0.98
    assert plan.steps[1].depends_on == ["features"]


def test_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        NormalizedFilters.model_validate({"unexpected": True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date_from", datetime(2026, 1, 1)),
        ("date_to", datetime(2026, 1, 1)),
    ],
)
def test_filters_require_timezone(field: str, value: datetime) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        NormalizedFilters.model_validate({field: value})


def test_filters_reject_reversed_ranges() -> None:
    with pytest.raises(ValidationError, match="date_from"):
        NormalizedFilters(date_from=NOW, date_to=NOW - timedelta(days=1))
    with pytest.raises(ValidationError, match="amount_min"):
        NormalizedFilters(amount_min=Decimal("20"), amount_max=Decimal("10"))


def test_filters_reject_duplicate_ids_and_invalid_codes() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        NormalizedFilters(customer_ids=["C1", "C1"])
    with pytest.raises(ValidationError):
        NormalizedFilters(country="india")
    with pytest.raises(ValidationError):
        NormalizedFilters(currency="usd")


def test_analysis_request_requires_aware_as_of_and_nonempty_query() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        AnalysisRequest(query="test", as_of=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        AnalysisRequest(query="", as_of=NOW)


def test_parsed_intent_bounds_confidence() -> None:
    with pytest.raises(ValidationError):
        ParsedIntent(
            intent=IntentType.SIMPLE_LOOKUP,
            target_scope=TargetScope.CUSTOMER,
            filters=NormalizedFilters(),
            confidence=1.1,
            parser_version="fixture.v1",
        )


def test_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        ValidatedPlan(
            strategy="invalid_plan",
            planner_version="fixture.v1",
            steps=[
                PlanStep(
                    step_id="sql",
                    tool=ToolName.SQL_LOOKUP,
                    operation="customer_lookup",
                    depends_on=["missing"],
                    reason="Lookup customer",
                )
            ],
        )


def test_plan_rejects_duplicate_step_ids() -> None:
    step = PlanStep(
        step_id="same",
        tool=ToolName.SQL_LOOKUP,
        operation="customer_lookup",
        reason="Lookup",
    )
    with pytest.raises(ValidationError, match="step_id values"):
        ValidatedPlan(
            strategy="invalid_plan",
            planner_version="fixture.v1",
            steps=[step, step.model_copy(update={"operation": "transaction_lookup"})],
        )


def test_plan_rejects_self_dependency_and_duplicate_dependencies() -> None:
    with pytest.raises(ValidationError, match="depend on itself"):
        ValidatedPlan(
            strategy="invalid_plan",
            planner_version="fixture.v1",
            steps=[
                PlanStep(
                    step_id="sql",
                    tool=ToolName.SQL_LOOKUP,
                    operation="customer_lookup",
                    depends_on=["sql"],
                    reason="Lookup",
                )
            ],
        )
    with pytest.raises(ValidationError, match="duplicates"):
        PlanStep(
            step_id="sql",
            tool=ToolName.SQL_LOOKUP,
            operation="customer_lookup",
            depends_on=["features", "features"],
            reason="Lookup",
        )


def test_plan_rejects_cycles() -> None:
    with pytest.raises(ValidationError, match="acyclic"):
        ValidatedPlan(
            strategy="invalid_plan",
            planner_version="fixture.v1",
            steps=[
                PlanStep(
                    step_id="first",
                    tool=ToolName.SQL_LOOKUP,
                    operation="customer_lookup",
                    depends_on=["second"],
                    reason="First",
                ),
                PlanStep(
                    step_id="second",
                    tool=ToolName.FEATURE_ENGINEERING,
                    operation="profile_features",
                    depends_on=["first"],
                    reason="Second",
                ),
            ],
        )


def test_plan_rejects_identical_tool_operations() -> None:
    with pytest.raises(ValidationError, match="identical"):
        ValidatedPlan(
            strategy="invalid_plan",
            planner_version="fixture.v1",
            steps=[
                PlanStep(
                    step_id="sql_one",
                    tool=ToolName.SQL_LOOKUP,
                    operation="customer_lookup",
                    parameters={"customer_id": "C1"},
                    reason="First",
                ),
                PlanStep(
                    step_id="sql_two",
                    tool=ToolName.SQL_LOOKUP,
                    operation="customer_lookup",
                    parameters={"customer_id": "C1"},
                    reason="Duplicate",
                ),
            ],
        )


def test_tool_result_status_invariants() -> None:
    payload = make_tool_result().model_dump()
    payload["status"] = ToolStatus.FAILED
    with pytest.raises(ValidationError, match="require error"):
        ToolResult.model_validate(payload)

    payload = make_tool_result().model_dump()
    payload["status"] = ToolStatus.SKIPPED
    with pytest.raises(ValidationError, match="require a reason"):
        ToolResult.model_validate(payload)

    payload = make_tool_result().model_dump()
    payload["error"] = ToolError(code="TIMEOUT", message="Timed out", retryable=True)
    with pytest.raises(ValidationError, match="only failed"):
        ToolResult.model_validate(payload)


def test_failed_tool_result_accepts_safe_error() -> None:
    result = ToolResult(
        tool=ToolName.EDA,
        operation="profile",
        status=ToolStatus.FAILED,
        scope=NormalizedFilters(),
        warnings=["EDA timed out"],
        duration_ms=1000,
        produced_at=NOW,
        provenance=ToolProvenance(source="fixture", query_or_version="eda.v1"),
        error=ToolError(code="TIMEOUT", message="Tool timed out", retryable=True),
    )
    assert result.error is not None
    assert result.error.retryable is True


def test_tool_result_requires_aware_timestamp() -> None:
    payload = make_tool_result().model_dump()
    payload["produced_at"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="timezone"):
        ToolResult.model_validate(payload)


def test_execution_summary_rejects_duplicate_or_overlapping_tools() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        ExecutionSummary(
            query="test",
            detected_intent=IntentType.SIMPLE_LOOKUP,
            route=RouteType.SIMPLE_LOOKUP,
            filters=NormalizedFilters(),
            tools_invoked=[ToolName.SQL_LOOKUP, ToolName.SQL_LOOKUP],
        )
    with pytest.raises(ValidationError, match="both invoked and skipped"):
        ExecutionSummary(
            query="test",
            detected_intent=IntentType.SIMPLE_LOOKUP,
            route=RouteType.SIMPLE_LOOKUP,
            filters=NormalizedFilters(),
            tools_invoked=[ToolName.SQL_LOOKUP],
            tools_skipped=[SkippedTool(tool=ToolName.SQL_LOOKUP, reason="not needed")],
        )


def test_execution_summary_requires_an_explicit_route() -> None:
    with pytest.raises(ValidationError, match="route"):
        ExecutionSummary.model_validate(
            {
                "query": "Show transactions over 10000",
                "detected_intent": "simple_lookup",
                "filters": {},
            }
        )


def test_final_response_supports_informational_result_without_risk() -> None:
    result = InformationalResult(
        summary="Three matching transactions",
        data={"count": 3},
        evidence_refs=["ev.sql.1"],
    )
    response = FinalResponse(
        request_id="req-1",
        generated_at=NOW,
        execution_summary=ExecutionSummary(
            query="Show transactions over 10000",
            detected_intent=IntentType.SIMPLE_LOOKUP,
            route=RouteType.SIMPLE_LOOKUP,
            filters=NormalizedFilters(amount_min=Decimal("10000")),
            tools_invoked=[ToolName.SQL_LOOKUP],
        ),
        results=[result],
        answer="Three transactions matched.",
    )

    dumped = response.model_dump(mode="json")
    assert dumped["results"][0]["result_type"] == "informational"
    assert "risk_level" not in dumped["results"][0]


def test_flagged_result_requires_valid_risk_and_evidence() -> None:
    result = FlaggedResult(
        entity_type=EntityType.CUSTOMER,
        entity_id="C123",
        risk_score=82.5,
        risk_level=RiskLevel.HIGH,
        confidence=0.9,
        reasons=["Structuring pattern"],
        escalation_action=EscalationAction.REPORT,
        evidence_refs=["ev.rules.1"],
    )
    assert result.risk_level is RiskLevel.HIGH

    with pytest.raises(ValidationError):
        FlaggedResult(
            entity_type=EntityType.CUSTOMER,
            entity_id="C123",
            risk_score=101,
            risk_level=RiskLevel.HIGH,
            confidence=0.9,
            reasons=["Invalid"],
            escalation_action=EscalationAction.REPORT,
            evidence_refs=[],
        )
    with pytest.raises(ValidationError, match="duplicates"):
        FlaggedResult.model_validate(result.model_dump() | {"evidence_refs": ["ev.1", "ev.1"]})


def test_chart_and_evidence_reference_validate_shape() -> None:
    chart = ChartSpec(
        chart_id="amount-distribution",
        chart_type=ChartType.HISTOGRAM,
        title="Amount distribution",
        data={"bins": [0, 100, 1000], "counts": [4, 2]},
        evidence_refs=["ev.eda.1"],
    )
    assert chart.chart_type is ChartType.HISTOGRAM

    with pytest.raises(ValidationError):
        EvidenceReference(
            evidence_id="bad id",
            tool=ToolName.EDA,
            kind="chart",
            json_path="not-a-path",
            label="Bad",
        )


def test_final_response_requires_aware_generated_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        FinalResponse(
            request_id="req-1",
            generated_at=datetime(2026, 1, 1),
            execution_summary=ExecutionSummary(
                query="test",
                detected_intent=IntentType.SIMPLE_LOOKUP,
                route=RouteType.SIMPLE_LOOKUP,
                filters=NormalizedFilters(),
            ),
            answer="No result.",
        )
