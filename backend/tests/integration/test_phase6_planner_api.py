"""API integration for Phase 6 dynamic planner path."""

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
                run_id="p6-api",
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
                transaction_id="TX-99",
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
                seed_run_id="p6-api",
            )
        )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    db = tmp_path / "p6.db"
    url = f"sqlite:///{db.as_posix()}"
    _seed(url)
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase6 API",
            "database_url": url,
            "data_dir": tmp_path / "data",
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def test_template_path_sql_only_unchanged(client: TestClient) -> None:
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
    assert body["execution_summary"]["tools_invoked"] == ["sql_lookup"]
    assert body["execution_summary"]["filters"]["amount_min"] == "10000"


def test_needs_planner_transaction_lookup_executes(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={
            "query": "Lookup transaction TX-99",
            "as_of": AS_OF.isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["needs_planner"] is True
    assert body["parsed_intent"]["filters"]["transaction_ids"] == ["TX-99"]
    assert body["execution_summary"]["tools_invoked"] == ["sql_lookup"]
    assert "eda" not in body["execution_summary"]["tools_invoked"]
    assert body["execution_summary"]["filters"]["transaction_ids"] == ["TX-99"]


def test_clarification_still_422(client: TestClient) -> None:
    response = client.post(
        "/api/v1/query",
        json={"query": "something vague about money", "as_of": AS_OF.isoformat()},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CLARIFICATION_REQUIRED"
