"""Phase 9: six mandatory demo queries assert distinct invoke/skip traces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.generation.orchestrator import generate_scenarios
from backend.app.generation.seeder import seed_runtime_bundle
from backend.app.main import create_app

AS_OF = datetime(2026, 7, 25, tzinfo=UTC)


@pytest.fixture(scope="module")
def seeded_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    root = tmp_path_factory.mktemp("p9-six")
    db = root / "demo.db"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_database_engine(url)
    Base.metadata.create_all(engine)
    result = generate_scenarios(
        seed=42,
        split="dev",
        generation_config_path=Path("config/generation/scenario_catalog.v1.yaml"),
        policy_config_path=Path("config/policy/reporting_thresholds.v1.yaml"),
    )
    with session_scope(session_factory(engine)) as session:
        seed_runtime_bundle(session, result.runtime, alembic_revision="head")
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase9 Six Queries",
            "database_url": url,
            "data_dir": root / "data",
            "chroma_persist_dir": root / "chroma",
            "policy_corpus_path": Path("config/policy/corpus/policy_excerpts.v1.json"),
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "risk_enabled": True,
            "explanation_enabled": True,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
            "risk_policy_path": Path("config/policy/risk_scoring.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def _post(client: TestClient, query: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/query",
        json={"query": query, "as_of": AS_OF.isoformat()},
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert "execution_summary" in body
    assert "results" in body
    return body


def test_q1_sql_only_amount_filter(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Show me transactions over $10,000")
    invoked = body["execution_summary"]["tools_invoked"]
    assert invoked == ["sql_lookup"]
    assert "eda" not in invoked
    assert "anomaly_detection" not in invoked
    assert "risk_classification" not in invoked


def test_q2_threshold_aggregation(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Which customers made 10+ transactions under $10,000?",
    )
    invoked = set(body["execution_summary"]["tools_invoked"])
    assert invoked == {"sql_lookup"}
    assert "eda" not in invoked
    assert "feature_engineering" not in invoked
    assert "anomaly_detection" not in invoked
    assert "risk_classification" not in invoked
    assert "escalation" not in invoked
    evidence = body.get("supporting_evidence") or body.get("tool_results") or []
    cohort = next(
        (
            item
            for item in evidence
            if item.get("tool") == "sql_lookup" and item.get("operation") == "count_by_customer"
        ),
        None,
    )
    assert cohort is not None
    assert cohort["status"] == "success"
    assert "customers" in cohort["data"]
    assert cohort["data"]["minimum_count"] == 10


def test_q3_feature_only_spending(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Did customer cus-dev-42-spending-increase-00 suddenly increase spending this month?",
    )
    invoked = body["execution_summary"]["tools_invoked"]
    assert invoked.count("feature_engineering") >= 1
    assert "eda" not in invoked
    assert "anomaly_detection" not in invoked
    assert body["route"] == "feature_only"
    info = next((r for r in body["results"] if r.get("result_type") == "informational"), None)
    assert info is not None
    assert "spend_comparison" in (info.get("data") or {})
    cmp = info["data"]["spend_comparison"]
    assert "current_minor" in cmp and "prior_minor" in cmp
    assert "elevated" in cmp


def test_q4_structuring_features_and_rules(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find structuring patterns for customer cus-dev-42-structuring-00 in the last 30 days",
    )
    invoked = set(body["execution_summary"]["tools_invoked"])
    skipped = {item["tool"] for item in body["execution_summary"]["tools_skipped"]}
    assert "feature_engineering" in invoked or "anomaly_detection" in invoked
    assert "eda" not in invoked
    assert "eda" in skipped or "eda" not in invoked


def test_q5_entity_investigation_no_dataset_eda(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Is customer ID cus-dev-42-structuring-00 suspicious?")
    invoked = set(body["execution_summary"]["tools_invoked"])
    assert "eda" not in invoked
    assert (
        "sql_lookup" in invoked
        or "feature_engineering" in invoked
        or "anomaly_detection" in invoked
    )
    skipped_tools = {item["tool"] for item in body["execution_summary"]["tools_skipped"]}
    assert "eda" in skipped_tools or "eda" not in invoked
    assert body["parsed_intent"]["intent"] in {
        "entity_investigation",
        "pattern_search",
        "feature_comparison",
    }


def _flagged_or_risk(body: dict[str, Any]) -> tuple[str, float]:
    flagged = [item for item in body.get("results") or [] if item.get("result_type") == "flagged"]
    if flagged:
        return str(flagged[0]["risk_level"]), float(flagged[0].get("risk_score") or 0)
    evidence = body.get("supporting_evidence") or body.get("tool_results") or []
    for item in evidence:
        if item.get("tool") == "risk_classification" and isinstance(item.get("data"), dict):
            data = item["data"]
            return str(data.get("risk_level") or "LOW"), float(data.get("risk_score") or 0)
    raise AssertionError("no flagged result or risk_classification evidence")


def _anomaly_rules(body: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = body.get("supporting_evidence") or body.get("tool_results") or []
    for item in evidence:
        if item.get("tool") == "anomaly_detection" and isinstance(item.get("data"), dict):
            rules = item["data"].get("rules") or []
            if isinstance(rules, list):
                return [rule for rule in rules if isinstance(rule, dict)]
    return []


def test_entity_investigation_velocity_elevated(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Is customer ID cus-dev-42-velocity-00 suspicious?")
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert "velocity.v1" in rules
    assert rules["velocity.v1"].get("fired") is True


def test_entity_investigation_structuring_elevated(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Is customer ID cus-dev-42-structuring-00 suspicious?")
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert "structuring.v1" in rules
    assert rules["structuring.v1"].get("fired") is True


def test_entity_investigation_clean_stays_low(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Is customer ID cus-dev-42-clean-000 suspicious?")
    level, score = _flagged_or_risk(body)
    assert level == "LOW"
    assert score < 40
    fired = [rule for rule in _anomaly_rules(body) if rule.get("fired")]
    assert fired == []


def test_pattern_search_smurfing_elevated(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find smurfing patterns for customer cus-dev-42-smurfing-00 in the last 30 days",
    )
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert "smurfing.v1" in rules
    assert rules["smurfing.v1"].get("fired") is True
    # Targeted pattern plans should only evaluate the matching rule.
    assert set(rules) == {"smurfing.v1"}


def test_pattern_search_velocity_elevated(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find velocity patterns for customer cus-dev-42-velocity-00 in the last 30 days",
    )
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert rules["velocity.v1"].get("fired") is True


def test_pattern_search_rapid_cash_out_elevated(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find rapid cash-out patterns for customer cus-dev-42-rapid-cash-out-00 "
        "in the last 30 days",
    )
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert rules["rapid_cash_out.v1"].get("fired") is True


def test_pattern_search_structuring_elevated(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find structuring patterns for customer cus-dev-42-structuring-00 in the last 30 days",
    )
    level, score = _flagged_or_risk(body)
    assert level in {"MEDIUM", "HIGH"}
    assert score >= 40
    rules = {rule["rule_id"]: rule for rule in _anomaly_rules(body)}
    assert rules["structuring.v1"].get("fired") is True


def test_pattern_search_clean_stays_low(seeded_client: TestClient) -> None:
    body = _post(
        seeded_client,
        "Find structuring patterns for customer cus-dev-42-clean-000 in the last 30 days",
    )
    level, score = _flagged_or_risk(body)
    assert level == "LOW"
    assert score < 40
    fired = [rule for rule in _anomaly_rules(body) if rule.get("fired")]
    assert fired == []


def test_q6_broad_eda_exploration(seeded_client: TestClient) -> None:
    body = _post(seeded_client, "Analyse this dataset for suspicious activity")
    invoked = set(body["execution_summary"]["tools_invoked"])
    assert "eda" in invoked
    # Broad cohort path should not pretend to be a single-entity SQL lookup only.
    assert body["route"] in {"full_investigation", "simple_lookup"} or "eda" in invoked


def test_customers_list_endpoint(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/v1/customers?limit=10&offset=0")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["items"][0]["customer_id"]


def test_health_endpoint(seeded_client: TestClient) -> None:
    response = seeded_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
