"""API integration for Phase 5 free-text routing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Account, Base, Customer, DatasetRun, Transaction
from backend.app.main import create_app

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)


def _seed(database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        session.add(
            DatasetRun(
                run_id="p5-api",
                run_kind="aml_seed",
                alembic_revision="head",
                record_counts={},
                created_at=START,
            )
        )
        session.flush()
        session.add(Customer(customer_id="123", created_at=START, status="active"))
        session.flush()
        session.add(
            Account(
                account_id="A1",
                customer_id="123",
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
                customer_id="123",
                account_id="A1",
                occurred_at=START + timedelta(days=20),
                amount_minor=1_500_000,
                currency="USD",
                direction="credit",
                transaction_type="wire",
                channel="online",
                country="US",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p5-api",
            )
        )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db = tmp_path / "p5.db"
    url = f"sqlite:///{db.as_posix()}"
    _seed(url)
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase5 API",
            "database_url": url,
            "data_dir": tmp_path / "data",
            "ollama_enabled": False,
            "ml_enabled": False,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def test_free_text_sql_only_query(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={
            "query": "Show me transactions over $10,000.",
            "as_of": AS_OF.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "simple_lookup"
    assert body["parsed_intent"]["intent"] == "simple_lookup"
    invoked = body["execution_summary"]["tools_invoked"]
    assert invoked == ["sql_lookup"]
    assert "eda" not in invoked
    assert "anomaly_detection" not in invoked


def test_free_text_feature_only_query(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={
            "query": "Did customer 123 suddenly increase spending this month?",
            "as_of": AS_OF.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "feature_only"
    assert "feature_engineering" in body["execution_summary"]["tools_invoked"]
    assert "eda" not in body["execution_summary"]["tools_invoked"]


def test_manual_plan_path_unchanged(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={
            "query": "manual",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["123"]},
            "route": "simple_lookup",
            "plan": {
                "strategy": "manual_sql",
                "planner_version": "test.v1",
                "steps": [
                    {
                        "step_id": "s1",
                        "tool": "sql_lookup",
                        "operation": "get_customer",
                        "parameters": {"customer_id": "123"},
                        "reason": "manual",
                    }
                ],
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["parsed_intent"] is None
    assert response.json()["execution_summary"]["tools_invoked"] == ["sql_lookup"]


def test_clarification_returns_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={"query": "something vague about money", "as_of": AS_OF.isoformat()},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CLARIFICATION_REQUIRED"


def test_investigation_create_free_text_sql_only(client: TestClient) -> None:
    response = client.post(
        "/api/v1/investigations",
        json={
            "query": "Show me transactions over $10,000.",
            "as_of": AS_OF.isoformat(),
            "request_id": "p5-inv-sql",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "simple_lookup"
    assert body["execution_summary"]["tools_invoked"] == ["sql_lookup"]
    assert "eda" not in body["execution_summary"]["tools_invoked"]
