"""Integration tests for Phase 4 graph execution and persisted traces."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import (
    Account,
    Base,
    Customer,
    DatasetRun,
    Transaction,
)
from backend.app.domain.enums import RouteType, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.main import create_app
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY
from backend.app.workflow.graph import GraphExecutor
from backend.app.workflow.intent import intent_from_route
from backend.app.workflow.state import InvestigationState

AS_OF = datetime(2026, 2, 1, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)
POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))


def _seed(database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        session.add(
            DatasetRun(
                run_id="p4-api",
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
                occurred_at=START + timedelta(days=3),
                amount_minor=1000,
                currency="USD",
                direction="credit",
                transaction_type="cash_deposit",
                channel="branch",
                country="US",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p4-api",
            )
        )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "p4.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    _seed(database_url)
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase4 API Test",
            "database_url": database_url,
            "data_dir": tmp_path / "data",
            "ml_enabled": False,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def _feature_plan() -> dict[str, object]:
    return {
        "strategy": "feature_only",
        "planner_version": "phase4.v1",
        "steps": [
            {
                "step_id": "f1",
                "tool": "feature_engineering",
                "operation": "compute_feature",
                "parameters": {
                    "feature_operation": "transaction_count",
                    "entity_ids": ["C1"],
                    "window_days": 60,
                },
                "reason": "feature-only",
            }
        ],
    }


def _sql_plan() -> dict[str, object]:
    return {
        "strategy": "sql_only",
        "planner_version": "phase4.v1",
        "steps": [
            {
                "step_id": "s1",
                "tool": "sql_lookup",
                "operation": "get_customer",
                "parameters": {"customer_id": "C1"},
                "reason": "lookup",
            }
        ],
    }


def test_plans_produce_different_invoked_sets(client: TestClient) -> None:
    feature = client.post(
        "/api/v1/investigations",
        json={
            "query": "feature",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _feature_plan(),
            "route": "feature_only",
            "request_id": "p4-feature",
        },
    )
    sql = client.post(
        "/api/v1/investigations",
        json={
            "query": "sql",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _sql_plan(),
            "route": "simple_lookup",
            "request_id": "p4-sql",
        },
    )
    assert feature.status_code == 200
    assert sql.status_code == 200
    feature_invoked = feature.json()["execution_summary"]["tools_invoked"]
    sql_invoked = sql.json()["execution_summary"]["tools_invoked"]
    assert feature_invoked != sql_invoked
    assert "eda" not in feature_invoked
    assert "anomaly_detection" not in sql_invoked
    assert "feature_engineering" in feature_invoked
    assert "sql_lookup" in sql_invoked

    fetched = client.get(f"/api/v1/investigations/{feature.json()['investigation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["execution_summary"]["tools_invoked"] == feature_invoked
    assert fetched.json()["status"] == feature.json()["status"]


def test_query_returns_execution_summary(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={
            "query": "sql query path",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _sql_plan(),
            "route": "simple_lookup",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["execution_summary"]["route"] == "simple_lookup"
    assert body["execution_summary"]["tools_invoked"] == ["sql_lookup"]
    assert body["status"] == "completed"


def test_graph_matches_direct_dispatch_payload(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'reg.db').as_posix()}"
    _seed(database_url)
    engine = create_database_engine(database_url)
    plan = ValidatedPlan(
        strategy="parity",
        planner_version="phase4.v1",
        steps=[
            PlanStep(
                step_id="s1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="parity",
            )
        ],
    )
    settings = Settings(environment="test", ml_enabled=False)
    with session_scope(session_factory(engine)) as session:
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=settings,
            filters=NormalizedFilters(customer_ids=["C1"]),
            as_of=AS_OF,
        )
        direct = TOOL_REGISTRY.dispatch(
            ToolName.SQL_LOOKUP,
            "get_customer",
            context=context,
            parameters={"customer_id": "C1"},
        )
        state = InvestigationState(
            request_id="parity",
            query="parity",
            route=RouteType.SIMPLE_LOOKUP,
            detected_intent=intent_from_route(RouteType.SIMPLE_LOOKUP),
            filters=NormalizedFilters(customer_ids=["C1"]),
            plan=plan,
            as_of=AS_OF,
        )
        outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=settings).execute(
            state,
            context=context,
        )
    graph_result = outcome.state.tool_results[0]
    assert graph_result.status == direct.status
    assert graph_result.data == direct.data
