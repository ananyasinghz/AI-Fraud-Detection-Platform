"""Unit tests for Phase 4 graph executor skip/timeout/retry policy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import IntentType, RouteType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolError, ToolProvenance, ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import make_result
from backend.app.tools.registry import TOOL_REGISTRY, ToolRegistry
from backend.app.workflow.execution_trace import ExecutionTrace
from backend.app.workflow.graph import GraphExecutor
from backend.app.workflow.intent import intent_from_route
from backend.app.workflow.state import InvestigationState

POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))
AS_OF = datetime(2026, 2, 1, tzinfo=UTC)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "node_timeout_seconds": 5.0,
        "node_max_retries": 1,
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _state(plan: ValidatedPlan, *, route: RouteType = RouteType.FEATURE_ONLY) -> InvestigationState:
    return InvestigationState(
        request_id="req-wf-1",
        query="unit workflow",
        route=route,
        detected_intent=intent_from_route(route),
        filters=NormalizedFilters(customer_ids=["C1"]),
        plan=plan,
        as_of=AS_OF,
        investigation_id="inv-wf-1",
    )


def test_intent_from_route_mapping() -> None:
    assert intent_from_route(RouteType.SIMPLE_LOOKUP) is IntentType.SIMPLE_LOOKUP
    assert intent_from_route(RouteType.FEATURE_ONLY) is IntentType.FEATURE_COMPARISON
    assert intent_from_route(RouteType.FULL_INVESTIGATION) is IntentType.ENTITY_INVESTIGATION


def test_trace_summary_invoked_skipped_disjoint() -> None:
    plan = ValidatedPlan(
        strategy="s",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="a",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="lookup",
            )
        ],
    )
    state = _state(plan)
    state.tools_invoked = [ToolName.SQL_LOOKUP]
    state.tools_skipped = []
    summary = ExecutionTrace().build_summary(state)
    assert summary.tools_invoked == [ToolName.SQL_LOOKUP]
    assert summary.tools_skipped == []


def test_dependency_skip_and_no_double_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'wf.db'}")
    Base.metadata.create_all(engine)
    plan = ValidatedPlan(
        strategy="dep",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="a",
                tool=ToolName.EDA,
                operation="cohort_profile",
                reason="required eda that will be forced to fail via monkeypatch",
                required=True,
            ),
            PlanStep(
                step_id="b",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_count",
                    "entity_ids": ["C1"],
                    "window_days": 30,
                },
                reason="depends on eda",
                depends_on=["a"],
                required=True,
            ),
        ],
    )

    def boom(
        tool: ToolName,
        operation: str,
        parameters: dict[str, Any],
        context: ToolContext,
        registry: ToolRegistry,
    ) -> ToolResult:
        del operation, parameters, registry
        if tool is ToolName.EDA:
            return make_result(
                tool=tool,
                operation="cohort_profile",
                status=ToolStatus.FAILED,
                scope=context.filters,
                duration_ms=1,
                provenance=ToolProvenance(source="eda", query_or_version="t"),
                error=ToolError(code="BOOM", message="required failed", retryable=False),
            )
        return make_result(
            tool=tool,
            operation="compute_feature",
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            duration_ms=1,
            provenance=ToolProvenance(source="feature", query_or_version="t"),
        )

    monkeypatch.setattr("backend.app.workflow.graph.run_tool_node", boom)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=_settings(),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=_settings()).execute(
            _state(plan, route=RouteType.FULL_INVESTIGATION),
            context=context,
        )
    assert outcome.status == "partial"
    skipped_tools = {item.tool for item in outcome.state.tools_skipped}
    assert ToolName.EDA in skipped_tools
    assert ToolName.FEATURE_ENGINEERING in skipped_tools
    reasons = {item.tool: item.reason for item in outcome.state.tools_skipped}
    assert reasons[ToolName.FEATURE_ENGINEERING] in {"DEPENDENCY_SKIPPED", "DEPENDENCY_FAILED"}
    terminal = [
        event
        for event in outcome.trace.events
        if event.event in {"succeeded", "failed", "skipped", "timed_out"}
    ]
    step_ids = [event.step_id for event in terminal]
    assert step_ids.count("a") == 1
    assert step_ids.count("b") == 1


def test_optional_failure_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'opt.db'}")
    Base.metadata.create_all(engine)

    def boom(
        tool: ToolName,
        operation: str,
        parameters: dict[str, Any],
        context: ToolContext,
        registry: ToolRegistry,
    ) -> ToolResult:
        del operation, parameters, registry
        if tool is ToolName.EDA:
            return make_result(
                tool=tool,
                operation="cohort_profile",
                status=ToolStatus.FAILED,
                scope=context.filters,
                duration_ms=1,
                provenance=ToolProvenance(source="eda", query_or_version="t"),
                error=ToolError(code="BOOM", message="optional failed", retryable=False),
            )
        return make_result(
            tool=tool,
            operation="classify",
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["PHASE_8_NOT_IMPLEMENTED"],
            duration_ms=1,
            provenance=ToolProvenance(source="risk", query_or_version="t"),
        )

    monkeypatch.setattr("backend.app.workflow.graph.run_tool_node", boom)
    plan = ValidatedPlan(
        strategy="opt",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="eda1",
                tool=ToolName.EDA,
                operation="cohort_profile",
                reason="optional eda",
                required=False,
            ),
            PlanStep(
                step_id="risk1",
                tool=ToolName.RISK_CLASSIFICATION,
                operation="classify",
                reason="after eda",
                depends_on=["eda1"],
                required=False,
            ),
        ],
    )
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=_settings(),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=_settings()).execute(
            _state(plan),
            context=context,
        )
    assert outcome.status == "partial"
    assert outcome.state.optional_degraded is True


def test_timeout_records_timed_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'to.db'}")
    Base.metadata.create_all(engine)

    def slow(*_args: object, **_kwargs: object) -> ToolResult:
        import time

        time.sleep(0.2)
        raise AssertionError("should have timed out")

    monkeypatch.setattr("backend.app.workflow.graph.run_tool_node", slow)
    plan = ValidatedPlan(
        strategy="timeout",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="slow1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="slow",
                required=True,
            )
        ],
    )
    settings = _settings(node_timeout_seconds=0.05, node_max_retries=0)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=settings,
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=settings).execute(
            _state(plan),
            context=context,
        )
    assert any(event.event == "timed_out" for event in outcome.trace.events)
    assert outcome.status in {"partial", "failed"}


def test_retryable_failure_retries_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'retry.db'}")
    Base.metadata.create_all(engine)
    calls = {"n": 0}

    def flaky(
        tool: ToolName,
        operation: str,
        parameters: dict[str, Any],
        context: ToolContext,
        registry: ToolRegistry,
    ) -> ToolResult:
        del tool, operation, parameters, registry
        calls["n"] += 1
        if calls["n"] == 1:
            return make_result(
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                status=ToolStatus.FAILED,
                scope=context.filters,
                duration_ms=1,
                provenance=ToolProvenance(source="sql", query_or_version="t"),
                error=ToolError(code="TEMP", message="retry me", retryable=True),
            )
        return make_result(
            tool=ToolName.SQL_LOOKUP,
            operation="get_customer",
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={"customer_id": "C1"},
            duration_ms=1,
            provenance=ToolProvenance(source="sql", query_or_version="t"),
        )

    monkeypatch.setattr("backend.app.workflow.graph.run_tool_node", flaky)
    plan = ValidatedPlan(
        strategy="retry",
        planner_version="t.v1",
        steps=[
            PlanStep(
                step_id="s1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="retry path",
            )
        ],
    )
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=_settings(),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=_settings()).execute(
            _state(plan, route=RouteType.SIMPLE_LOOKUP),
            context=context,
        )
    assert calls["n"] == 2
    assert outcome.status == "completed"
    assert ToolName.SQL_LOOKUP in outcome.state.tools_invoked
