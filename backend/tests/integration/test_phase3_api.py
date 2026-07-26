"""Integration tests for Phase 3 HTTP APIs with an isolated SQLite DB."""

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
from backend.app.main import create_app
from backend.app.ml.fraud_scorer import FraudScorer
from backend.app.ml.prepare import SplitConfig, prepare_ml_data
from backend.app.ml.schema import sha256_file
from backend.app.ml.training import TrainingConfig, train_models
from backend.tests.helpers.ulb_seed import seed_ulb_attached_transaction

FIXTURE = Path("backend/tests/fixtures/creditcard_tiny.csv")
AS_OF = datetime(2026, 2, 1, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)


def _train_selected(tmp_path: Path) -> Path:
    prepare_ml_data(
        source_path=FIXTURE,
        raw_copy_path=tmp_path / "raw" / "creditcard.csv",
        split_dir=tmp_path / "splits",
        evaluation_dir=tmp_path / "evaluation",
        config=SplitConfig(
            version="fixture_split.v1",
            seed=42,
            train_ratio=0.70,
            validation_ratio=0.15,
            test_ratio=0.15,
            expected_rows=22,
            expected_fraud_rows=11,
            expected_sha256=sha256_file(FIXTURE),
            grouping="exact_match_all_30_non_label_columns",
        ),
    )
    model_root = tmp_path / "models"
    train_models(
        split_dir=tmp_path / "splits",
        model_root=model_root,
        config=TrainingConfig.model_validate(
            {
                "version": "fixture_training.v1",
                "preprocessing_version": "preprocessing.v1",
                "seed": 42,
                "threshold": {
                    "metric": "f1",
                    "recall_floor": 0.8,
                    "tie_breaking": ["highest_f1", "highest_recall", "highest_threshold"],
                },
                "logistic_regression": {
                    "class_weight": "balanced",
                    "max_iter": 200,
                    "solver": "lbfgs",
                },
                "random_forest": {
                    "class_weight": "balanced_subsample",
                    "n_estimators": 10,
                    "max_depth": 4,
                    "min_samples_leaf": 1,
                    "n_jobs": 1,
                },
            }
        ),
    )
    selected = model_root / "selected"
    assert FraudScorer.from_artifact(selected)
    return selected


def _seed_api_db(database_url: str) -> None:
    engine = create_database_engine(database_url)
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        session.add(
            DatasetRun(
                run_id="api-seed",
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
                transaction_id="T-SYN",
                customer_id="C1",
                account_id="A1",
                occurred_at=START + timedelta(days=5),
                amount_minor=2500,
                currency="USD",
                direction="credit",
                transaction_type="cash_deposit",
                channel="branch",
                country="US",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="api-seed",
            )
        )
        session.flush()
        seed_ulb_attached_transaction(session, transaction_id="T-ULB", fixture_row=0)


@pytest.fixture
def api_client(tmp_path: Path) -> TestClient:
    db_path = tmp_path / "api.db"
    database_url = f"sqlite:///{db_path}"
    _seed_api_db(database_url)
    selected = _train_selected(tmp_path / "ml")
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase3 API Test",
            "database_url": database_url,
            "data_dir": tmp_path / "data",
            "ml_enabled": True,
            "ml_model_dir": selected,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def _feature_plan() -> dict[str, object]:
    return {
        "strategy": "feature_only",
        "planner_version": "phase3.v1",
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
                "reason": "feature-only answer",
            }
        ],
    }


def _hybrid_plan() -> dict[str, object]:
    return {
        "strategy": "hybrid_anomaly",
        "planner_version": "phase3.v1",
        "steps": [
            {
                "step_id": "a1",
                "tool": "anomaly_detection",
                "operation": "detect",
                "parameters": {
                    "mode": "hybrid",
                    "transaction_id": "T-ULB",
                    "entity_id": "C1",
                },
                "reason": "hybrid signals",
            }
        ],
    }


def test_query_executes_supplied_plan(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/v1/query",
        json={
            "query": "feature only via query",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _feature_plan(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tool_results"][0]["tool"] == "feature_engineering"
    assert "feature_engineering" in body["answer"]


def test_investigations_produce_distinct_tool_traces(api_client: TestClient) -> None:
    first = api_client.post(
        "/api/v1/investigations",
        json={
            "query": "feature only",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _feature_plan(),
            "route": "feature_only",
            "request_id": "inv-req-feature",
        },
    )
    second = api_client.post(
        "/api/v1/investigations",
        json={
            "query": "hybrid anomaly",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["C1"]},
            "plan": _hybrid_plan(),
            "route": "full_investigation",
            "request_id": "inv-req-hybrid",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 200
    first_tools = [item["tool"] for item in first.json()["tool_results"]]
    second_tools = [item["tool"] for item in second.json()["tool_results"]]
    assert first_tools != second_tools
    fetched = api_client.get(f"/api/v1/investigations/{first.json()['investigation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["tool_results"][0]["tool"] == "feature_engineering"


def test_customers_transactions_and_score_paths(api_client: TestClient) -> None:
    customer = api_client.get("/api/v1/customers/C1")
    assert customer.status_code == 200
    assert customer.json()["customer_id"] == "C1"

    synthetic = api_client.get("/api/v1/transactions/T-SYN")
    assert synthetic.status_code == 200
    assert synthetic.json()["ml_eligible"] is False

    skipped = api_client.post("/api/v1/transactions/T-SYN/score")
    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["reason"] == "ML_INELIGIBLE"

    scored = api_client.post("/api/v1/transactions/T-ULB/score")
    assert scored.status_code == 200
    body = scored.json()
    assert body["status"] == "scored"
    assert 0.0 <= body["ml_score"] <= 1.0


def test_alert_idempotency_transitions_and_history(api_client: TestClient) -> None:
    payload = {
        "entity_type": "customer",
        "entity_id": "C1",
        "finding_code": "VELOCITY_SIGNAL",
        "severity": "medium",
        "evidence_snapshot_ref": "ev.alert.velocity",
        "policy_version": "reporting_thresholds.v1",
        "investigation_window_start": AS_OF.isoformat(),
        "investigation_window_end": (AS_OF + timedelta(days=7)).isoformat(),
        "request_id": "alert-create-1",
    }
    first = api_client.post("/api/v1/alerts", json=payload)
    second = api_client.post("/api/v1/alerts", json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["alert_id"] == second.json()["alert_id"]
    alert_id = first.json()["alert_id"]

    missing_reason = api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={
            "status": "in_review",
            "reviewer_id": "rev-1",
            "reason": "",
            "request_id": "alert-patch-bad",
        },
    )
    assert missing_reason.status_code == 422

    to_review = api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={
            "status": "in_review",
            "reviewer_id": "rev-1",
            "reason": "starting review",
            "request_id": "alert-patch-1",
        },
    )
    assert to_review.status_code == 200
    assert to_review.json()["status"] == "in_review"

    to_dismissed = api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={
            "status": "dismissed",
            "reviewer_id": "rev-1",
            "reason": "false positive",
            "request_id": "alert-patch-2",
        },
    )
    assert to_dismissed.status_code == 200

    bad_transition = api_client.patch(
        f"/api/v1/alerts/{alert_id}",
        json={
            "status": "in_review",
            "reviewer_id": "rev-1",
            "reason": "reopen illegally",
            "request_id": "alert-patch-3",
        },
    )
    assert bad_transition.status_code == 409
    assert bad_transition.json()["error"]["code"] == "INVALID_TRANSITION"

    detail = api_client.get(f"/api/v1/alerts/{alert_id}")
    assert detail.status_code == 200
    history = detail.json()["history"]
    assert len(history) == 3
    assert history[-1]["to_status"] == "dismissed"
    assert detail.json()["status"] == history[-1]["to_status"]

    queue = api_client.get("/api/v1/alerts", params={"status": "dismissed"})
    assert queue.status_code == 200
    assert queue.json()["total"] >= 1
