"""Unit tests for Phase 8 response aggregation and disabled flags."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import (
    IntentType,
    RiskLevel,
    RouteType,
    ToolName,
    ToolStatus,
)
from backend.app.domain.evidence import EvidenceReference, ToolProvenance, ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.domain.responses import FlaggedResult, InformationalResult
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY, ToolRegistry
from backend.app.workflow.execution_trace import ExecutionTrace
from backend.app.workflow.nodes.aggregate import build_final_response
from backend.app.workflow.state import InvestigationState

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)
POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))


def _tr(
    tool: ToolName,
    operation: str,
    data: dict[str, Any],
    *,
    status: ToolStatus = ToolStatus.SUCCESS,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        operation=operation,
        status=status,
        produced_at=AS_OF,
        scope=NormalizedFilters(customer_ids=["C1"]),
        data=data,
        duration_ms=1,
        evidence=[
            EvidenceReference(
                evidence_id=f"{tool.value}.{operation}.1",
                tool=tool,
                kind="tool_result",
                json_path="$.data",
                label=operation,
            )
        ],
        provenance=ToolProvenance(source=tool.value, query_or_version="t.v1"),
    )


def test_aggregate_emits_flagged_for_medium_verified() -> None:
    plan = ValidatedPlan(
        strategy="s",
        planner_version="t",
        steps=[
            PlanStep(
                step_id="a",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="x",
            )
        ],
    )
    state = InvestigationState(
        request_id="req-agg",
        query="q",
        route=RouteType.FULL_INVESTIGATION,
        detected_intent=IntentType.ENTITY_INVESTIGATION,
        filters=NormalizedFilters(customer_ids=["C1"]),
        plan=plan,
        as_of=AS_OF,
    )
    state.tool_results = [
        _tr(
            ToolName.VERIFICATION,
            "verify_risk_consistency",
            {
                "risk_score": 55,
                "risk_level": "MEDIUM",
                "confidence": 0.8,
                "entity_id": "C1",
                "entity_type": "customer",
                "reasons": ["rule fired"],
                "evidence_ids": ["verification.verify_risk_consistency.1"],
            },
        ),
        _tr(
            ToolName.ESCALATION,
            "recommend",
            {
                "entity_id": "C1",
                "entity_type": "customer",
                "risk_score": 55,
                "risk_level": "MEDIUM",
                "escalation_action": "review",
                "reasons": ["rule fired"],
                "evidence_ids": ["verification.verify_risk_consistency.1"],
            },
        ),
        _tr(
            ToolName.EXPLANATION,
            "explain",
            {"summary": "Entity C1 assessed at MEDIUM.", "source": "template"},
        ),
    ]
    state.tools_invoked = [
        ToolName.VERIFICATION,
        ToolName.ESCALATION,
        ToolName.EXPLANATION,
    ]
    final = build_final_response(state, ExecutionTrace(), status="completed")
    assert any(isinstance(item, FlaggedResult) for item in final.results)
    flagged = next(item for item in final.results if isinstance(item, FlaggedResult))
    assert flagged.risk_level is RiskLevel.MEDIUM
    assert "MEDIUM" in final.answer or "Flagged" in final.answer


def test_aggregate_skips_low_without_explanation_success() -> None:
    plan = ValidatedPlan(
        strategy="s",
        planner_version="t",
        steps=[
            PlanStep(
                step_id="a",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="x",
            )
        ],
    )
    state = InvestigationState(
        request_id="req-low",
        query="q",
        route=RouteType.FULL_INVESTIGATION,
        detected_intent=IntentType.ENTITY_INVESTIGATION,
        filters=NormalizedFilters(customer_ids=["C1"]),
        plan=plan,
        as_of=AS_OF,
    )
    state.tool_results = [
        _tr(
            ToolName.VERIFICATION,
            "verify_risk_consistency",
            {
                "risk_score": 10,
                "risk_level": "LOW",
                "confidence": 0.5,
                "entity_id": "C1",
                "entity_type": "customer",
                "reasons": ["baseline"],
                "evidence_ids": ["e1"],
            },
        ),
        _tr(
            ToolName.ESCALATION,
            "recommend",
            {
                "entity_id": "C1",
                "entity_type": "customer",
                "escalation_action": "monitor",
                "reasons": ["baseline"],
                "evidence_ids": ["e1"],
            },
        ),
    ]
    final = build_final_response(state, ExecutionTrace(), status="completed")
    assert all(isinstance(item, InformationalResult) for item in final.results)


def test_risk_disabled_skips_handlers(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'dis.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=Settings(environment="test", risk_enabled=False, explanation_enabled=False),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        risk = TOOL_REGISTRY.dispatch(ToolName.RISK_CLASSIFICATION, "classify", context=context)
        ver = TOOL_REGISTRY.dispatch(ToolName.VERIFICATION, "verify_evidence", context=context)
        expl = TOOL_REGISTRY.dispatch(ToolName.EXPLANATION, "explain", context=context)
        assert risk.status is ToolStatus.SKIPPED
        assert ver.status is ToolStatus.SKIPPED
        assert expl.status is ToolStatus.SKIPPED


def test_adapters_unknown_operation_and_unknown_tool(tmp_path: Path) -> None:
    from backend.app.workflow.nodes.adapters import run_tool_node

    engine = create_database_engine(f"sqlite:///{tmp_path / 'ad.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=Settings(environment="test"),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        )
        failed = run_tool_node(
            tool=ToolName.SQL_LOOKUP,
            operation="drop_table",
            parameters={},
            context=context,
            registry=TOOL_REGISTRY,
        )
        assert failed.status is ToolStatus.FAILED
        assert failed.error is not None
        assert failed.error.code == "UNKNOWN_OPERATION"

        empty = ToolRegistry()
        skipped = run_tool_node(
            tool=ToolName.SQL_LOOKUP,
            operation="get_customer",
            parameters={"customer_id": "C1"},
            context=context,
            registry=empty,
        )
        assert skipped.status is ToolStatus.SKIPPED
        assert "UNKNOWN_TOOL" in skipped.warnings


def test_aggregate_low_with_explanation_and_partial_status() -> None:
    plan = ValidatedPlan(
        strategy="s",
        planner_version="t",
        steps=[
            PlanStep(
                step_id="a",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="x",
            )
        ],
    )
    state = InvestigationState(
        request_id="req-low-expl",
        query="q",
        route=RouteType.FULL_INVESTIGATION,
        detected_intent=IntentType.EXPLANATION_REQUEST,
        filters=NormalizedFilters(customer_ids=["C1"]),
        plan=plan,
        as_of=AS_OF,
    )
    state.tool_results = [
        _tr(
            ToolName.VERIFICATION,
            "verify_risk_consistency",
            {
                "risk_score": 12,
                "risk_level": "LOW",
                "confidence": 0.5,
                "entity_id": "C1",
                "entity_type": "not-a-real-type",
                "reasons": [],
                "evidence_ids": [],
            },
        ),
        _tr(
            ToolName.ESCALATION,
            "recommend",
            {
                "entity_id": "C1",
                "entity_type": "not-a-real-type",
                "escalation_action": "monitor",
                "reasons": [],
                "evidence_ids": [],
            },
        ),
        _tr(
            ToolName.EXPLANATION,
            "explain",
            {"summary": "low risk explanation", "source": "template"},
        ),
        _tr(
            ToolName.EDA,
            "cohort_profile",
            {
                "charts": [
                    {
                        "chart_id": "c1",
                        "title": "t",
                        "chart_type": "bar",
                        "data": {"labels": ["a"], "values": [1]},
                    }
                ]
            },
        ),
    ]
    final = build_final_response(state, ExecutionTrace(), status="partial")
    assert any(isinstance(item, FlaggedResult) for item in final.results)
    assert any(isinstance(item, InformationalResult) for item in final.results)
    assert final.charts


def test_phase8_handlers_blocked_and_customer_classify(tmp_path: Path) -> None:
    from backend.app.domain.evidence import ToolError

    engine = create_database_engine(f"sqlite:///{tmp_path / 'block.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=Settings(environment="test", ollama_enabled=False),
            filters=NormalizedFilters(customer_ids=["C1"]),
            as_of=AS_OF,
            request_id="req-block",
        )
        failed_verify = ToolResult(
            tool=ToolName.VERIFICATION,
            operation="verify_evidence",
            status=ToolStatus.FAILED,
            produced_at=AS_OF,
            scope=NormalizedFilters(customer_ids=["C1"]),
            data={"ok": False, "block_risk": True},
            duration_ms=1,
            provenance=ToolProvenance(source="verification", query_or_version="t.v1"),
            error=ToolError(code="X", message="blocked", retryable=False),
        )
        context.prior_results = [failed_verify]
        skipped = TOOL_REGISTRY.dispatch(
            ToolName.RISK_CLASSIFICATION, "classify_customer", context=context
        )
        assert skipped.status is ToolStatus.SKIPPED
        assert "BLOCKED_BY_EVIDENCE_VERIFICATION" in skipped.warnings

        context.prior_results = [
            _tr(
                ToolName.ANOMALY_DETECTION,
                "detect",
                {"rules": [{"rule_id": "R1", "severity": "high", "fired": True}]},
            ),
            _tr(
                ToolName.VERIFICATION,
                "verify_evidence",
                {
                    "ok": True,
                    "block_risk": False,
                    "evidence_ids": ["anomaly_detection.detect.1"],
                    "confidence_cap": 0.7,
                },
            ),
        ]
        classified = TOOL_REGISTRY.dispatch(
            ToolName.RISK_CLASSIFICATION, "classify_customer", context=context
        )
        assert classified.status is ToolStatus.SUCCESS
        assert classified.data["entity_type"] == "customer"

        context.prior_results = [*context.prior_results, classified]
        consist = TOOL_REGISTRY.dispatch(
            ToolName.VERIFICATION, "verify_risk_consistency", context=context
        )
        assert consist.status is ToolStatus.SUCCESS
        context.prior_results = [*context.prior_results, consist]
        esc = TOOL_REGISTRY.dispatch(ToolName.ESCALATION, "recommend", context=context)
        assert esc.status is ToolStatus.SUCCESS
        context.prior_results = [*context.prior_results, esc]
        expl = TOOL_REGISTRY.dispatch(ToolName.EXPLANATION, "explain", context=context)
        assert expl.status is ToolStatus.SUCCESS
        assert expl.data.get("source") in {"template", "template_fallback", "ollama"}
