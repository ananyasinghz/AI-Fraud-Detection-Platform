"""Tool registry dispatch and envelope checks."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import (
    TOOL_REGISTRY,
    UnknownToolOperationError,
)

POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))
AS_OF = datetime(2026, 2, 1, tzinfo=UTC)


def _context(session: Session) -> ToolContext:
    return ToolContext(
        session=session,
        policy=POLICY,
        settings=Settings(environment="test"),
        filters=NormalizedFilters(),
        as_of=AS_OF,
    )


def test_registry_rejects_unknown_tool_and_operation(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'reg.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        context = _context(session)
        with pytest.raises(UnknownToolOperationError):
            TOOL_REGISTRY.dispatch(ToolName.VERIFICATION, "run", context=context)
        with pytest.raises(UnknownToolOperationError):
            TOOL_REGISTRY.dispatch(ToolName.GRAPH_ANALYSIS, "run", context=context)
        with pytest.raises(UnknownToolOperationError):
            TOOL_REGISTRY.dispatch(ToolName.SQL_LOOKUP, "drop_table", context=context)


def test_phase8_tools_registered_and_require_verified_risk(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'stub.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        context = _context(session)
        risk = TOOL_REGISTRY.dispatch(
            ToolName.RISK_CLASSIFICATION,
            "classify",
            context=context,
        )
        explanation = TOOL_REGISTRY.dispatch(
            ToolName.EXPLANATION,
            "explain",
            context=context,
        )
        assert risk.status is ToolStatus.SUCCESS
        assert risk.duration_ms >= 0
        assert risk.provenance.source == "risk_classification"
        assert explanation.status is ToolStatus.FAILED
        assert explanation.error is not None
        assert explanation.error.code == "MISSING_VERIFIED_RISK"


def test_execute_plan_orders_dependencies(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'plan.db'}")
    Base.metadata.create_all(engine)
    plan = ValidatedPlan(
        strategy="feature_then_stub",
        planner_version="test.v1",
        steps=[
            PlanStep(
                step_id="b",
                tool=ToolName.RISK_CLASSIFICATION,
                operation="classify",
                reason="after eda",
                depends_on=["a"],
            ),
            PlanStep(
                step_id="a",
                tool=ToolName.EDA,
                operation="cohort_profile",
                reason="profile first",
            ),
        ],
    )
    with session_scope(session_factory(engine)) as session:
        results = TOOL_REGISTRY.execute_plan(plan, context=_context(session))
    assert [item.operation for item in results] == ["cohort_profile", "classify"]
    assert results[0].tool is ToolName.EDA
    assert results[0].scope == NormalizedFilters()
