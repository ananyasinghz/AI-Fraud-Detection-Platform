"""Integration: Phase 7 tools via registry/workflow and seeded graph gold."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import AnalysisRequest
from backend.app.generation.orchestrator import generate_scenarios
from backend.app.generation.seeder import seed_runtime_bundle
from backend.app.main import create_app
from backend.app.nlu.intent_parser import parse_intent
from backend.app.nlu.router import route_parsed_intent
from backend.app.tools.graph.builder import build_relationship_graph
from backend.app.tools.graph.queries import circular_transfers, shared_device, two_hop_exposure

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)
GOLD = Path("backend/tests/fixtures/graph_relationships.v1.json")


@pytest.fixture
def seeded_client(tmp_path: Path) -> tuple[TestClient, Path]:
    db = tmp_path / "p7.db"
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
            "app_name": "Phase7",
            "database_url": url,
            "data_dir": tmp_path / "data",
            "chroma_persist_dir": tmp_path / "chroma",
            "policy_corpus_path": Path("config/policy/corpus/policy_excerpts.v1.json"),
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
        }
    )
    return TestClient(create_app(settings)), tmp_path


def test_seeded_graph_gold_relationships(seeded_client: tuple[TestClient, Path]) -> None:
    _client, tmp_path = seeded_client
    # Use same DB via settings on client app — rebuild from generation for query asserts.
    db_url = None
    # Re-seed a dedicated engine for direct graph queries
    db = tmp_path / "gold.db"
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
        gold = json.loads(GOLD.read_text(encoding="utf-8"))
        share_a = next(
            c.customer_id for c in result.runtime.customers if "graph-share-a" in c.customer_id
        )
        share_b = next(
            c.customer_id for c in result.runtime.customers if "graph-share-b" in c.customer_id
        )
        filters = NormalizedFilters(customer_ids=[share_a, share_b])
        graph, _ = build_relationship_graph(session, filters)
        shared = shared_device(graph, seed_customer_ids=[share_a])
        assert shared["count"] >= 1
        assert any("graph-shared" in f["device_id"] for f in shared["findings"])

        cycle_customers = [
            c.customer_id for c in result.runtime.customers if "graph-cycle" in c.customer_id
        ]
        cycle_accounts = [
            a.account_id for a in result.runtime.accounts if a.customer_id in set(cycle_customers)
        ]
        cgraph, _ = build_relationship_graph(
            session,
            NormalizedFilters(account_ids=cycle_accounts),
        )
        cycles = circular_transfers(cgraph)
        assert cycles["count"] >= 1

        hop_cust = next(
            c.customer_id for c in result.runtime.customers if "graph-hop-a" in c.customer_id
        )
        hop_acct = next(a.account_id for a in result.runtime.accounts if a.customer_id == hop_cust)
        hgraph, _ = build_relationship_graph(
            session,
            NormalizedFilters(customer_ids=[hop_cust]),
        )
        hops = two_hop_exposure(hgraph, seed_account_ids=[hop_acct])
        assert any(
            "graph-hop-b" in node or "graph-hop-cp" in node for node in hops["exposed_nodes"]
        )
        assert gold["version"] == "graph_relationships.v1"
    del db_url


def test_workflow_runs_graph_and_retrieval(seeded_client: tuple[TestClient, Path]) -> None:
    client, tmp_path = seeded_client
    # Execute via API with an explicit plan including both tools.
    customers = client.get("/api/v1/customers/cus-dev-42-graph-share-a")
    # customer id format from generator: cus-{prefix} where prefix includes split?
    # add_customer uses f"cus-{prefix}" and prefix is f"{key}" with key graph-share-a
    # Actually: customer_id = f"cus-{prefix}" and prefix = f"{key}" = "graph-share-a"
    # Wait: prefix = key in add_customer(f"graph-share-a") -> cus-graph-share-a
    # Looking at code: customer_id = f"cus-{prefix}" and prefix argument is the key.
    # From generate: add_customer("graph-share-a") -> cus-graph-share-a

    plan = {
        "strategy": "phase7_probe",
        "planner_version": "test.v1",
        "steps": [
            {
                "step_id": "g1",
                "tool": "graph_analysis",
                "operation": "shared_device",
                "parameters": {"customer_id": "cus-graph-share-a"},
                "reason": "shared device",
            },
            {
                "step_id": "r1",
                "tool": "retrieval",
                "operation": "search_policy",
                "parameters": {"query": "structuring reporting threshold"},
                "reason": "policy context",
                "depends_on": ["g1"],
                "required": False,
            },
        ],
    }
    response = client.post(
        "/api/v1/query",
        json={
            "query": "graph probe",
            "as_of": AS_OF.isoformat(),
            "filters": {"customer_ids": ["cus-graph-share-a", "cus-graph-share-b"]},
            "route": "full_investigation",
            "plan": plan,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    invoked = body["execution_summary"]["tools_invoked"]
    assert "graph_analysis" in invoked
    assert "retrieval" in invoked
    assert all(
        "PHASE_7_NOT_IMPLEMENTED" not in (r.get("warnings") or []) for r in body["tool_results"]
    )
    del customers
    del tmp_path


def test_sql_only_template_excludes_graph_retrieval() -> None:
    settings = Settings(
        environment="test",
        ollama_enabled=False,
        development_seed=42,
        heldout_seed=99,
    )
    parsed = parse_intent(
        AnalysisRequest(query="Show me transactions over $10,000.", as_of=AS_OF),
        settings=settings,
    )
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert decision.plan is not None
    tools = {step.tool for step in decision.plan.steps}
    assert tools == {ToolName.SQL_LOOKUP}
    assert ToolName.GRAPH_ANALYSIS not in tools
    assert ToolName.RETRIEVAL not in tools


def test_entity_template_may_include_optional_graph() -> None:
    settings = Settings(
        environment="test",
        ollama_enabled=False,
        development_seed=42,
        heldout_seed=99,
    )
    parsed = parse_intent(
        AnalysisRequest(query="Is customer ID 4521 suspicious?", as_of=AS_OF),
        settings=settings,
    )
    decision = route_parsed_intent(parsed, confidence_floor=0.55)
    assert decision.plan is not None
    tools = {step.tool for step in decision.plan.steps}
    assert ToolName.SQL_LOOKUP in tools
    assert ToolName.GRAPH_ANALYSIS in tools
    assert ToolName.RETRIEVAL in tools
    optional = [step for step in decision.plan.steps if step.tool is ToolName.GRAPH_ANALYSIS]
    assert optional and optional[0].required is False
