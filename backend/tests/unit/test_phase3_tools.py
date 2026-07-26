"""Unit coverage for SQL, feature, EDA, and anomaly tool facades."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import (
    Account,
    Base,
    Customer,
    DatasetRun,
    Transaction,
)
from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.filters import NormalizedFilters
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY
from backend.tests.helpers.ulb_seed import seed_ulb_attached_transaction

POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))
AS_OF = datetime(2026, 2, 1, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)


def _seed_basic(session: Session) -> None:
    session.add(
        DatasetRun(
            run_id="p3-tools",
            run_kind="aml_seed",
            alembic_revision="head",
            record_counts={},
            created_at=START,
        )
    )
    session.flush()
    session.add(Customer(customer_id="C1", created_at=START, status="active"))
    session.flush()
    session.add(
        Account(
            account_id="A1",
            customer_id="C1",
            account_type="checking",
            currency="USD",
            country="US",
            opened_at=START,
            status="active",
        )
    )
    session.flush()
    session.add(
        Transaction(
            transaction_id="T1",
            customer_id="C1",
            account_id="A1",
            occurred_at=START + timedelta(days=10),
            amount_minor=5000,
            currency="USD",
            direction="credit",
            transaction_type="cash_deposit",
            channel="branch",
            country=None,
            ml_eligible=False,
            data_source="synthetic",
            seed_run_id="p3-tools",
        )
    )
    session.flush()


def _context(session: Session, filters: NormalizedFilters | None = None) -> ToolContext:
    return ToolContext(
        session=session,
        policy=POLICY,
        settings=Settings(environment="test"),
        filters=filters or NormalizedFilters(customer_ids=["C1"]),
        as_of=AS_OF,
    )


def test_sql_and_feature_tools_preserve_scope(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'tools.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        _seed_basic(session)
        filters = NormalizedFilters(customer_ids=["C1"])
        context = _context(session, filters)
        customer = TOOL_REGISTRY.dispatch(
            ToolName.SQL_LOOKUP,
            "get_customer",
            context=context,
            parameters={"customer_id": "C1"},
        )
        listed = TOOL_REGISTRY.dispatch(
            ToolName.SQL_LOOKUP,
            "list_transactions",
            context=context,
            parameters={},
        )
        feature = TOOL_REGISTRY.dispatch(
            ToolName.FEATURE_ENGINEERING,
            "compute_feature",
            context=context,
            parameters={
                "feature_operation": "transaction_count",
                "entity_ids": ["C1"],
                "window_days": 60,
            },
        )
        assert customer.status is ToolStatus.SUCCESS
        assert customer.scope == filters
        assert listed.data["count"] == 1
        assert listed.scope == filters
        assert feature.status is ToolStatus.SUCCESS
        assert feature.scope == filters


def test_eda_emits_chart_specs_and_skips_labels_by_default(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'eda.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        _seed_basic(session)
        context = _context(session)
        profile = TOOL_REGISTRY.dispatch(ToolName.EDA, "cohort_profile", context=context)
        missing = TOOL_REGISTRY.dispatch(ToolName.EDA, "missingness_quality", context=context)
        amounts = TOOL_REGISTRY.dispatch(ToolName.EDA, "amount_distribution", context=context)
        blocked = TOOL_REGISTRY.dispatch(ToolName.EDA, "class_balance", context=context)
        allowed = TOOL_REGISTRY.dispatch(
            ToolName.EDA,
            "class_balance",
            context=context,
            parameters={"allow_labels": True},
        )
        for result in (profile, missing, amounts, allowed):
            charts = result.data.get("charts", [])
            assert isinstance(charts, list)
            for raw in charts:
                ChartSpec.model_validate(raw)
        assert blocked.status is ToolStatus.SKIPPED
        assert "LABELS_NOT_ALLOWLISTED" in blocked.warnings
        assert "class_counts" not in allowed.data
        assert "scenario_label" not in str(allowed.data)


def test_anomaly_skips_ml_for_ineligible_synthetic(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'anom.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        _seed_basic(session)
        context = _context(session)
        result = TOOL_REGISTRY.dispatch(
            ToolName.ANOMALY_DETECTION,
            "detect",
            context=context,
            parameters={"mode": "ml_only", "transaction_id": "T1", "entity_id": "C1"},
        )
        assert result.status is ToolStatus.SKIPPED
        assert "ML_INELIGIBLE" in result.warnings
        ml_payload = result.data["ml"]
        assert isinstance(ml_payload, dict)
        assert ml_payload["reason"] == "ML_INELIGIBLE"


def test_anomaly_hybrid_with_ulb_fixture_without_scorer(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'hybrid.db'}")
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        _seed_basic(session)
        seed_ulb_attached_transaction(session, transaction_id="TX-ULB-0")
        context = _context(session, NormalizedFilters(customer_ids=["C1", "C-ULB"]))
        result = TOOL_REGISTRY.dispatch(
            ToolName.ANOMALY_DETECTION,
            "detect",
            context=context,
            parameters={
                "mode": "hybrid",
                "transaction_id": "TX-ULB-0",
                "entity_id": "C1",
            },
        )
        assert result.status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}
        ml_payload = result.data["ml"]
        assert isinstance(ml_payload, dict)
        assert ml_payload["reason"] == "SCORER_UNAVAILABLE"
