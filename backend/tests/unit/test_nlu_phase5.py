"""Unit tests for Phase 5 date normalizer, parser, router, and templates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.domain.enums import IntentType, RouteType, ToolName
from backend.app.domain.intent import AnalysisRequest
from backend.app.nlu.date_normalizer import apply_relative_dates, normalize_relative_window
from backend.app.nlu.intent_parser import parse_intent
from backend.app.nlu.router import route_parsed_intent
from backend.app.nlu.templates import plan_sql_amount_lookup

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "ollama_enabled": False,
        "development_seed": 42,
        "heldout_seed": 99,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def test_date_normalizer_relative_windows() -> None:
    start, end = normalize_relative_window("last_30_days", as_of=AS_OF)
    assert start is not None and end is not None
    assert (end - start).days == 30
    month_start, month_end = normalize_relative_window("this_month", as_of=AS_OF)
    assert month_start == datetime(2026, 2, 1, tzinfo=UTC)
    assert month_end == AS_OF
    absolute_from = datetime(2026, 1, 1, tzinfo=UTC)
    resolved_from, _resolved_to, ambiguities = apply_relative_dates(
        as_of=AS_OF,
        relative_date="last_30_days",
        date_from=absolute_from,
        date_to=AS_OF,
    )
    assert resolved_from == absolute_from
    assert "relative_date_ignored_absolute_present" in ambiguities


def test_parser_fallback_mandatory_sql_only() -> None:
    request = AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF)
    parsed = parse_intent(request, settings=_settings())
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert parsed.intent is IntentType.SIMPLE_LOOKUP
    assert parsed.filters.amount_min == Decimal("10000")
    assert decision.route is RouteType.SIMPLE_LOOKUP
    assert decision.plan is not None
    tools = {step.tool for step in decision.plan.steps}
    assert tools == {ToolName.SQL_LOOKUP}
    assert ToolName.EDA in decision.tools_skipped_expected


def test_parser_retry_then_fallback() -> None:
    calls = {"n": 0}

    def bad_transport(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        return {"message": {"content": "not-json"}}

    request = AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF)
    parsed = parse_intent(
        request,
        settings=_settings(ollama_enabled=True),
        transport=bad_transport,
    )
    assert calls["n"] == 2
    assert "+fallback" in parsed.parser_version
    assert parsed.intent is IntentType.SIMPLE_LOOKUP


def test_parser_mocked_ollama_success() -> None:
    def ok_transport(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": {
                "content": (
                    '{"intent":"pattern_search","target_scope":"cohort","confidence":0.91,'
                    '"customer_ids":[],"account_ids":[],"transaction_ids":[],'
                    '"pattern_type":"structuring","relative_date":"last_30_days",'
                    '"currency":"USD","ambiguities":[]}'
                )
            }
        }

    request = AnalysisRequest(
        query="Find structuring patterns in the last 30 days.",
        as_of=AS_OF,
    )
    parsed = parse_intent(
        request,
        settings=_settings(ollama_enabled=True),
        transport=ok_transport,
    )
    assert parsed.intent is IntentType.PATTERN_SEARCH
    assert parsed.filters.pattern_type is not None
    assert parsed.filters.date_from is not None


def test_router_low_confidence_does_not_broaden_to_eda() -> None:
    request = AnalysisRequest(query="something vague about money", as_of=AS_OF)
    parsed = parse_intent(request, settings=_settings())
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert decision.plan is None
    assert decision.clarification
    assert ToolName.EDA in decision.tools_skipped_expected


def test_invalid_customer_id_does_not_invent_match() -> None:
    request = AnalysisRequest(query="Is customer ID !!!bad!!! suspicious?", as_of=AS_OF)
    parsed = parse_intent(request, settings=_settings())
    assert parsed.filters.customer_ids == []
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert decision.plan is None or "4521" not in str(decision.filters.customer_ids)


def test_sql_template_excludes_eda_and_anomaly() -> None:
    from backend.app.domain.filters import NormalizedFilters

    plan = plan_sql_amount_lookup(NormalizedFilters(amount_min=Decimal("10000")))
    tools = {step.tool for step in plan.steps}
    assert tools == {ToolName.SQL_LOOKUP}


@pytest.mark.parametrize(
    ("query", "intent"),
    [
        ("Find structuring patterns in the last 30 days.", IntentType.PATTERN_SEARCH),
        ("Which customers made 10+ transactions under $10,000?", IntentType.THRESHOLD_AGGREGATION),
        ("Is customer ID 4521 suspicious?", IntentType.ENTITY_INVESTIGATION),
        ("Did customer 123 suddenly increase spending this month?", IntentType.FEATURE_COMPARISON),
        ("Show me transactions over $10,000.", IntentType.SIMPLE_LOOKUP),
        ("Analyse this dataset for suspicious activity.", IntentType.BROAD_EXPLORATION),
    ],
)
def test_mandatory_queries_intent(query: str, intent: IntentType) -> None:
    parsed = parse_intent(AnalysisRequest(query=query, as_of=AS_OF), settings=_settings())
    assert parsed.intent is intent


def test_date_normalizer_additional_tokens_and_errors() -> None:
    assert normalize_relative_window(None, as_of=AS_OF) == (None, None)
    assert normalize_relative_window("none", as_of=AS_OF) == (None, None)
    start7, end7 = normalize_relative_window("last_7_days", as_of=AS_OF)
    assert start7 is not None and end7 is not None
    assert (end7 - start7).days == 7
    start90, _ = normalize_relative_window("last_90_days", as_of=AS_OF)
    assert start90 == AS_OF - timedelta(days=90)
    full_start, full_end = normalize_relative_window("this_month_full", as_of=AS_OF)
    assert full_start == datetime(2026, 2, 1, tzinfo=UTC)
    assert full_end == datetime(2026, 3, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="timezone"):
        normalize_relative_window("last_30_days", as_of=datetime(2026, 2, 15))
    with pytest.raises(ValueError, match="unsupported"):
        normalize_relative_window("next_week", as_of=AS_OF)
    _, _, ambs = apply_relative_dates(
        as_of=AS_OF,
        relative_date="bogus_token",
        date_from=None,
        date_to=None,
    )
    assert ambs == ["unresolved_relative_date:bogus_token"]
    assert apply_relative_dates(
        as_of=AS_OF,
        relative_date=None,
        date_from=None,
        date_to=None,
    ) == (None, None, [])


def test_draft_sanitizes_invalid_enums_and_ids() -> None:
    from backend.app.domain.enums import TargetScope
    from backend.app.nlu.intent_parser import draft_to_parsed_intent
    from backend.app.nlu.schemas import IntentDraft

    draft = IntentDraft.model_construct(
        intent=IntentType.SIMPLE_LOOKUP,
        target_scope=TargetScope.DATASET,
        confidence=0.9,
        customer_ids=["ok-1", "!!!", "", "ok-1"],
        account_ids=["A1"],
        transaction_ids=["T1"],
        country="usa",
        currency="us",
        pattern_type="not_a_pattern",
        relative_date="last_7_days",
        ambiguities=[],
    )
    parsed = draft_to_parsed_intent(
        draft,
        request=AnalysisRequest(query="x", as_of=AS_OF),
        parser_version="test",
    )
    assert parsed.filters.customer_ids == ["ok-1"]
    assert parsed.filters.account_ids == ["A1"]
    assert parsed.filters.transaction_ids == ["T1"]
    assert parsed.filters.country is None
    assert parsed.filters.currency is None
    assert parsed.filters.pattern_type is None
    assert parsed.target_scope is TargetScope.CUSTOMER
    assert any("invalid_customer_id" in item for item in parsed.ambiguities)


def test_plan_pattern_search_is_typology_aware() -> None:
    from backend.app.domain.enums import PatternType, TargetScope
    from backend.app.domain.filters import NormalizedFilters
    from backend.app.domain.intent import ParsedIntent
    from backend.app.nlu.pattern_plans import spec_for_pattern
    from backend.app.nlu.templates import plan_pattern_search

    for pattern in PatternType:
        spec = spec_for_pattern(pattern)
        parsed = ParsedIntent(
            intent=IntentType.PATTERN_SEARCH,
            target_scope=TargetScope.CUSTOMER,
            filters=NormalizedFilters(
                customer_ids=["cus-1"],
                pattern_type=pattern,
                currency="USD",
            ),
            confidence=0.9,
            parser_version="t",
        )
        plan = plan_pattern_search(parsed)
        assert plan.strategy == spec.strategy
        feat_ops = [
            step.parameters.get("feature_operation")
            for step in plan.steps
            if step.tool is ToolName.FEATURE_ENGINEERING
        ]
        assert feat_ops == list(spec.feature_operations)
        anom = next(step for step in plan.steps if step.tool is ToolName.ANOMALY_DETECTION)
        if spec.rule_ids is None:
            assert "rule_ids" not in anom.parameters
        else:
            assert anom.parameters.get("rule_ids") == list(spec.rule_ids)


def test_pattern_search_without_customer_clarifies() -> None:
    parsed = parse_intent(
        AnalysisRequest(query="Find smurfing patterns in the last 30 days.", as_of=AS_OF),
        settings=_settings(),
    )
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert parsed.intent is IntentType.PATTERN_SEARCH
    assert decision.plan is None
    assert decision.clarification
    assert "customer id" in decision.clarification.lower()


def test_fallback_detects_all_pattern_keywords() -> None:
    from backend.app.domain.enums import PatternType
    from backend.app.nlu.fallback import extract_fallback

    cases = [
        ("Find velocity patterns for customer C1", PatternType.VELOCITY),
        ("Find rapid cash-out for customer C1", PatternType.RAPID_CASH_OUT),
        ("Find round number patterns for customer C1", PatternType.ROUND_NUMBER),
        ("Find profile deviation for customer C1", PatternType.PROFILE_DEVIATION),
        ("Find high-risk country patterns for customer C1", PatternType.HIGH_RISK_COUNTRY),
        ("Find smurfing for customer C1", PatternType.SMURFING),
        ("Find structuring for customer C1", PatternType.STRUCTURING),
    ]
    for query, expected in cases:
        draft = extract_fallback(query)
        assert draft.pattern_type is expected, query
        assert draft.intent is IntentType.PATTERN_SEARCH


def test_router_routes_and_templates_for_mandatory_family() -> None:
    from backend.app.nlu.templates import (
        plan_broad_exploration,
        plan_entity_investigation,
        plan_feature_only,
        plan_pattern_search,
        plan_simple_customer_lookup,
        plan_threshold_aggregation,
        plan_transaction_scoring,
    )

    cases = [
        "Find structuring patterns in the last 30 days.",
        "Which customers made 10+ transactions under $10,000?",
        "Is customer ID 4521 suspicious?",
        "Did customer 123 suddenly increase spending this month?",
        "Show me transactions over $10,000.",
        "Analyse this dataset for suspicious activity.",
        "Lookup customer ID A1",
        "Score transaction TX-1 for fraud",
        "Explain why customer 12 was flagged",
        "Get customer 9001 details",
    ]
    for query in cases:
        parsed = parse_intent(AnalysisRequest(query=query, as_of=AS_OF), settings=_settings())
        decision = route_parsed_intent(parsed, confidence_floor=0.55)
        if decision.plan is not None:
            assert 1 <= len(decision.plan.steps) <= 20

    # Direct template builders (coverage for optional branches).
    parsed_feat = parse_intent(
        AnalysisRequest(
            query="Did customer 123 suddenly increase spending this month?", as_of=AS_OF
        ),
        settings=_settings(),
    )
    assert plan_feature_only(parsed_feat).steps[0].tool is ToolName.FEATURE_ENGINEERING
    assert len(plan_feature_only(parsed_feat).steps) == 2
    assert plan_feature_only(parsed_feat).steps[1].parameters.get("window_role") == "prior"
    assert plan_pattern_search(parsed_feat).steps[0].tool is ToolName.FEATURE_ENGINEERING
    assert plan_entity_investigation(parsed_feat).steps[0].tool is ToolName.SQL_LOOKUP
    assert plan_threshold_aggregation(parsed_feat.filters).steps[0].tool is ToolName.SQL_LOOKUP
    assert plan_threshold_aggregation(parsed_feat.filters).steps[0].operation == "count_by_customer"
    assert plan_simple_customer_lookup(parsed_feat).steps[0].tool is ToolName.SQL_LOOKUP
    assert plan_broad_exploration().steps[0].tool is ToolName.EDA
    parsed_txn = parse_intent(
        AnalysisRequest(query="Score transaction TX-1 for fraud", as_of=AS_OF),
        settings=_settings(),
    )
    assert plan_transaction_scoring(parsed_txn).steps[0].tool is ToolName.SQL_LOOKUP


def test_router_clarifies_feature_and_entity_without_ids() -> None:
    from backend.app.domain.enums import TargetScope
    from backend.app.domain.filters import NormalizedFilters
    from backend.app.domain.intent import ParsedIntent

    feature = ParsedIntent(
        intent=IntentType.FEATURE_COMPARISON,
        target_scope=TargetScope.CUSTOMER,
        filters=NormalizedFilters(),
        confidence=0.9,
        parser_version="t",
    )
    decision = route_parsed_intent(feature, confidence_floor=0.55)
    assert decision.plan is None
    assert decision.clarification

    entity = ParsedIntent(
        intent=IntentType.ENTITY_INVESTIGATION,
        target_scope=TargetScope.CUSTOMER,
        filters=NormalizedFilters(),
        confidence=0.9,
        parser_version="t",
    )
    assert route_parsed_intent(entity, confidence_floor=0.55).plan is None

    scoring = ParsedIntent(
        intent=IntentType.TRANSACTION_SCORING,
        target_scope=TargetScope.TRANSACTION,
        filters=NormalizedFilters(),
        confidence=0.9,
        parser_version="t",
    )
    assert route_parsed_intent(scoring, confidence_floor=0.55).plan is None

    lookup = ParsedIntent(
        intent=IntentType.SIMPLE_LOOKUP,
        target_scope=TargetScope.DATASET,
        filters=NormalizedFilters(),
        confidence=0.9,
        parser_version="t",
    )
    assert route_parsed_intent(lookup, confidence_floor=0.55).plan is None


def test_resolve_for_execution_manual_and_nl() -> None:
    from backend.app.domain.filters import NormalizedFilters
    from backend.app.domain.plan import PlanStep, ValidatedPlan
    from backend.app.services.routing import resolve_for_execution

    plan = ValidatedPlan(
        strategy="manual_sql",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="s1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "123"},
                reason="manual",
            )
        ],
    )
    manual = resolve_for_execution(
        query="manual",
        as_of=AS_OF,
        filters=NormalizedFilters(customer_ids=["123"]),
        plan=plan,
        route=RouteType.SIMPLE_LOOKUP,
        detected_intent=None,
        settings=_settings(),
    )
    assert manual.parsed_intent is None
    assert manual.plan.strategy == "manual_sql"

    nl = resolve_for_execution(
        query="Show me transactions over $10,000.",
        as_of=AS_OF,
        filters=NormalizedFilters(),
        plan=None,
        route=RouteType.SIMPLE_LOOKUP,
        detected_intent=None,
        settings=_settings(),
    )
    assert nl.parsed_intent is not None
    assert nl.route is RouteType.SIMPLE_LOOKUP

    with pytest.raises(AppError) as exc:
        resolve_for_execution(
            query="something vague about money",
            as_of=AS_OF,
            filters=NormalizedFilters(),
            plan=None,
            route=RouteType.SIMPLE_LOOKUP,
            detected_intent=None,
            settings=_settings(),
        )
    assert exc.value.code == "CLARIFICATION_REQUIRED"


def test_parser_ollama_success_with_response_field() -> None:
    def transport(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "response": (
                '{"intent":"simple_lookup","target_scope":"dataset","confidence":0.9,'
                '"amount_min":"10000","currency":"USD","ambiguities":[]}'
            )
        }

    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=_settings(ollama_enabled=True),
        transport=transport,
    )
    assert parsed.intent is IntentType.SIMPLE_LOOKUP
    assert parsed.filters.amount_min == Decimal("10000")
