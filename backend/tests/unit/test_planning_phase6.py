"""Unit tests for Phase 6 semantic validator and dynamic planner."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.domain.enums import IntentType, RouteType, TargetScope, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import AnalysisRequest, ParsedIntent
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.nlu.intent_parser import parse_intent
from backend.app.nlu.router import route_parsed_intent
from backend.app.planning.fallback import safe_template_for_intent
from backend.app.planning.planner import plan_for_intent
from backend.app.planning.validator import validate_plan_semantics
from backend.app.services.routing import resolve_for_execution

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "ollama_enabled": False,
        "planner_enabled": False,
        "development_seed": 42,
        "heldout_seed": 99,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _parsed(
    intent: IntentType,
    *,
    customer_ids: list[str] | None = None,
    transaction_ids: list[str] | None = None,
    amount_min: Decimal | None = None,
    scope: TargetScope = TargetScope.DATASET,
    confidence: float = 0.9,
) -> ParsedIntent:
    return ParsedIntent(
        intent=intent,
        target_scope=scope,
        filters=NormalizedFilters(
            customer_ids=customer_ids or [],
            transaction_ids=transaction_ids or [],
            amount_min=amount_min,
        ),
        confidence=confidence,
        parser_version="test",
    )


def test_validator_rejects_unknown_and_phase8_tools() -> None:
    parsed = _parsed(IntentType.SIMPLE_LOOKUP, amount_min=Decimal("10000"))
    bad = {
        "strategy": "bad_plan",
        "planner_version": "t.v1",
        "steps": [
            {
                "step_id": "r1",
                "tool": "risk_classification",
                "operation": "classify",
                "parameters": {},
                "reason": "nope",
            }
        ],
    }
    result = validate_plan_semantics(bad, parsed=parsed, planner_version="t.v1")
    assert not result.ok
    assert any("tool_not_whitelisted" in r for r in result.reasons)

    unknown_op = {
        "strategy": "bad_op",
        "planner_version": "t.v1",
        "steps": [
            {
                "step_id": "s1",
                "tool": "sql_lookup",
                "operation": "drop_table",
                "parameters": {},
                "reason": "bad",
            }
        ],
    }
    result2 = validate_plan_semantics(unknown_op, parsed=parsed, planner_version="t.v1")
    assert not result2.ok
    assert any("unknown_operation" in r for r in result2.reasons)


def test_validator_rejects_over_broad_eda_on_entity_scope() -> None:
    parsed = _parsed(
        IntentType.ENTITY_INVESTIGATION,
        customer_ids=["4521"],
        scope=TargetScope.CUSTOMER,
    )
    draft = {
        "strategy": "too_broad",
        "planner_version": "t.v1",
        "steps": [
            {
                "step_id": "e1",
                "tool": "eda",
                "operation": "cohort_profile",
                "parameters": {},
                "reason": "broad",
            }
        ],
    }
    result = validate_plan_semantics(draft, parsed=parsed, planner_version="t.v1")
    assert not result.ok
    assert "over_broad_eda_on_entity_scope" in result.reasons


def test_validator_accepts_sql_only_and_feature_only() -> None:
    sql_parsed = _parsed(IntentType.SIMPLE_LOOKUP, amount_min=Decimal("10000"))
    sql_plan = ValidatedPlan(
        strategy="sql_only",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="list_transactions",
                parameters={},
                reason="amount filter",
            )
        ],
    )
    assert validate_plan_semantics(sql_plan, parsed=sql_parsed, planner_version="t.v1").ok

    feat_parsed = _parsed(
        IntentType.FEATURE_COMPARISON,
        customer_ids=["123"],
        scope=TargetScope.CUSTOMER,
    )
    feat_plan = ValidatedPlan(
        strategy="feature_only",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="f1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_total",
                    "entity_ids": ["123"],
                    "window_days": 30,
                },
                reason="spend",
            )
        ],
    )
    assert validate_plan_semantics(feat_plan, parsed=feat_parsed, planner_version="t.v1").ok


def test_validator_rejects_duplicate_and_cycle_via_domain() -> None:
    from pydantic import ValidationError

    parsed = _parsed(IntentType.SIMPLE_LOOKUP, amount_min=Decimal("10000"))
    with pytest.raises(ValidationError):
        ValidatedPlan(
            strategy="dup",
            planner_version="t.v1",
            steps=[
                PlanStep(
                    step_id="a",
                    tool=ToolName.SQL_LOOKUP,
                    operation="list_transactions",
                    parameters={},
                    reason="one",
                ),
                PlanStep(
                    step_id="b",
                    tool=ToolName.SQL_LOOKUP,
                    operation="list_transactions",
                    parameters={},
                    reason="two",
                ),
            ],
        )
    result = validate_plan_semantics(
        {
            "strategy": "cycle",
            "planner_version": "t.v1",
            "steps": [
                {
                    "step_id": "a",
                    "tool": "sql_lookup",
                    "operation": "get_customer",
                    "parameters": {"customer_id": "1"},
                    "depends_on": ["b"],
                    "reason": "a",
                },
                {
                    "step_id": "b",
                    "tool": "sql_lookup",
                    "operation": "get_transaction",
                    "parameters": {"transaction_id": "T"},
                    "depends_on": ["a"],
                    "reason": "b",
                },
            ],
        },
        parsed=parsed,
        planner_version="t.v1",
    )
    assert not result.ok


def test_planner_disabled_uses_fallback() -> None:
    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=_settings(),
    )
    result = plan_for_intent(parsed, settings=_settings(planner_enabled=False))
    assert result.used_fallback
    assert result.plan is not None
    tools = {step.tool for step in result.plan.steps}
    assert tools == {ToolName.SQL_LOOKUP}
    assert ToolName.EDA not in tools
    assert ToolName.RISK_CLASSIFICATION not in tools


def test_planner_retry_then_fallback() -> None:
    calls = {"n": 0}

    def bad_transport(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        return {"message": {"content": "not-json"}}

    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=_settings(),
    )
    result = plan_for_intent(
        parsed,
        settings=_settings(planner_enabled=True, ollama_enabled=True),
        transport=bad_transport,
    )
    assert calls["n"] == 2
    assert result.used_fallback
    assert result.plan is not None


def test_planner_mocked_ollama_success() -> None:
    def ok_transport(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": {
                "content": (
                    '{"strategy":"sql_amount_lookup","steps":[{'
                    '"step_id":"sql1","tool":"sql_lookup","operation":"list_transactions",'
                    '"parameters":{},"depends_on":[],"reason":"amount threshold","required":true}]}'
                )
            }
        }

    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=_settings(),
    )
    result = plan_for_intent(
        parsed,
        settings=_settings(planner_enabled=True, ollama_enabled=True),
        transport=ok_transport,
    )
    assert not result.used_fallback
    assert result.source == "ollama"
    assert result.plan is not None
    assert result.plan.steps[0].tool is ToolName.SQL_LOOKUP


def test_planner_never_keeps_phase8_steps_from_llm() -> None:
    def bad_tools(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": {
                "content": (
                    '{"strategy":"risky","steps":[{'
                    '"step_id":"r1","tool":"explanation","operation":"explain",'
                    '"parameters":{},"depends_on":[],"reason":"bad","required":true}]}'
                )
            }
        }

    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=_settings(),
    )
    result = plan_for_intent(
        parsed,
        settings=_settings(planner_enabled=True, ollama_enabled=True),
        transport=bad_tools,
    )
    assert result.used_fallback
    assert result.plan is not None
    assert all(step.tool is not ToolName.EXPLANATION for step in result.plan.steps)


def test_mandatory_forced_planner_invoke_skip() -> None:
    cases = [
        (
            "Show me transactions over $10,000.",
            {ToolName.SQL_LOOKUP},
            {ToolName.EDA, ToolName.ANOMALY_DETECTION},
        ),
        (
            "Did customer 123 suddenly increase spending this month?",
            {ToolName.FEATURE_ENGINEERING},
            {ToolName.EDA},
        ),
        (
            "Find structuring patterns in the last 30 days.",
            {ToolName.FEATURE_ENGINEERING, ToolName.ANOMALY_DETECTION},
            {ToolName.EDA},
        ),
        (
            "Analyse this dataset for suspicious activity.",
            {ToolName.EDA},
            set(),
        ),
        (
            "Is customer ID 4521 suspicious?",
            {ToolName.SQL_LOOKUP, ToolName.FEATURE_ENGINEERING},
            {ToolName.EDA},
        ),
        (
            "Which customers made 10+ transactions under $10,000?",
            {ToolName.SQL_LOOKUP, ToolName.FEATURE_ENGINEERING},
            {ToolName.EDA, ToolName.ANOMALY_DETECTION},
        ),
    ]
    for query, must_include, must_skip in cases:
        parsed = parse_intent(AnalysisRequest(query=query, as_of=AS_OF), settings=_settings())
        result = plan_for_intent(parsed, settings=_settings(), force=True)
        assert result.plan is not None, query
        tools = {step.tool for step in result.plan.steps}
        assert must_include.issubset(tools), (query, tools)
        assert tools.isdisjoint(must_skip), (query, tools)


def test_router_transaction_lookup_needs_planner() -> None:
    parsed = parse_intent(
        AnalysisRequest(query="Lookup transaction TX-99", as_of=AS_OF),
        settings=_settings(),
    )
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert decision.plan is None
    assert decision.needs_planner is True


def test_resolve_needs_planner_path_builds_plan() -> None:
    resolved = resolve_for_execution(
        query="Lookup transaction TX-99",
        as_of=AS_OF,
        filters=NormalizedFilters(),
        plan=None,
        route=RouteType.SIMPLE_LOOKUP,
        detected_intent=None,
        settings=_settings(),
    )
    assert resolved.needs_planner is True
    assert resolved.plan.steps[0].tool is ToolName.SQL_LOOKUP
    assert resolved.plan.steps[0].operation == "get_transaction"
    assert resolved.filters.transaction_ids == ["TX-99"]


def test_resolve_template_path_unchanged_for_amount() -> None:
    resolved = resolve_for_execution(
        query="Show me transactions over $10,000.",
        as_of=AS_OF,
        filters=NormalizedFilters(),
        plan=None,
        route=RouteType.SIMPLE_LOOKUP,
        detected_intent=None,
        settings=_settings(),
    )
    assert resolved.plan_source == "template"
    assert resolved.needs_planner is False
    tools = {step.tool for step in resolved.plan.steps}
    assert tools == {ToolName.SQL_LOOKUP}


def test_resolve_clarification_still_422() -> None:
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


def test_safe_template_none_for_explanation() -> None:
    parsed = _parsed(IntentType.EXPLANATION_REQUEST, confidence=0.8)
    assert safe_template_for_intent(parsed, planner_version="t.v1") is None
