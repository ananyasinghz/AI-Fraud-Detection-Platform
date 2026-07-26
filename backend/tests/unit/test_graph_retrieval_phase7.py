"""Unit tests for Phase 7 graph analysis and policy retrieval."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import (
    Account,
    Base,
    Counterparty,
    Customer,
    DatasetRun,
    Device,
    Transaction,
)
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.filters import NormalizedFilters
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.graph.builder import build_relationship_graph
from backend.app.tools.graph.queries import circular_transfers, shared_device, two_hop_exposure
from backend.app.tools.graph.tool import handle_graph_analysis
from backend.app.tools.retrieval.corpus import load_corpus
from backend.app.tools.retrieval.tool import handle_retrieval

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": "sqlite:///:memory:",
        "data_dir": tmp_path / "data",
        "chroma_persist_dir": tmp_path / "chroma",
        "policy_corpus_path": Path("config/policy/corpus/policy_excerpts.v1.json"),
        "graph_enabled": True,
        "retrieval_enabled": True,
        "development_seed": 42,
        "heldout_seed": 99,
        "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def _seed_graph_db(session: Session) -> None:
    session.add(
        DatasetRun(
            run_id="p7",
            run_kind="aml_seed",
            alembic_revision="head",
            record_counts={},
            created_at=START,
        )
    )
    session.flush()
    session.add_all(
        [
            Customer(customer_id="C1", created_at=START, status="active"),
            Customer(customer_id="C2", created_at=START, status="active"),
        ]
    )
    session.flush()
    session.add_all(
        [
            Account(
                account_id="A1",
                customer_id="C1",
                account_type="checking",
                currency="USD",
                country="US",
                opened_at=START,
                status="active",
            ),
            Account(
                account_id="A2",
                customer_id="C2",
                account_type="checking",
                currency="USD",
                country="US",
                opened_at=START,
                status="active",
            ),
        ]
    )
    session.add(
        Device(device_id="DSHARED", device_type="mobile", first_seen_at=START, last_seen_at=AS_OF)
    )
    session.add(
        Counterparty(counterparty_id="CP1", display_name="Hop CP", country="US", kind="merchant")
    )
    session.flush()
    session.add_all(
        [
            Transaction(
                transaction_id="T1",
                customer_id="C1",
                account_id="A1",
                occurred_at=START + timedelta(days=10),
                amount_minor=1000,
                currency="USD",
                direction="debit",
                transaction_type="card_purchase",
                channel="mobile",
                country="US",
                device_id="DSHARED",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p7",
            ),
            Transaction(
                transaction_id="T2",
                customer_id="C2",
                account_id="A2",
                occurred_at=START + timedelta(days=11),
                amount_minor=2000,
                currency="USD",
                direction="debit",
                transaction_type="card_purchase",
                channel="mobile",
                country="US",
                device_id="DSHARED",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p7",
            ),
            Transaction(
                transaction_id="T3",
                customer_id="C1",
                account_id="A1",
                occurred_at=START + timedelta(days=12),
                amount_minor=5000,
                currency="USD",
                direction="debit",
                transaction_type="wire_transfer",
                channel="online",
                country="US",
                counterparty_account_id="A2",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p7",
            ),
            Transaction(
                transaction_id="T4",
                customer_id="C2",
                account_id="A2",
                occurred_at=START + timedelta(days=12, hours=2),
                amount_minor=4000,
                currency="USD",
                direction="debit",
                transaction_type="wire_transfer",
                channel="online",
                country="US",
                counterparty_account_id="A1",
                counterparty_id="CP1",
                ml_eligible=False,
                data_source="synthetic",
                seed_run_id="p7",
            ),
        ]
    )


@pytest.fixture
def graph_session(tmp_path: Path) -> Iterator[Session]:
    db = tmp_path / "g.db"
    engine = create_database_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        _seed_graph_db(session)
        session.commit()
    # reopen
    with session_scope(factory) as session:
        yield session


def test_shared_device_and_cycle_queries(graph_session: Session) -> None:
    filters = NormalizedFilters(customer_ids=["C1", "C2"])
    graph, warnings = build_relationship_graph(graph_session, filters)
    assert "EMPTY_GRAPH_SCOPE" not in warnings
    shared = shared_device(graph, seed_customer_ids=["C1"])
    assert shared["count"] >= 1
    assert any(f["device_id"] == "DSHARED" for f in shared["findings"])
    cycles = circular_transfers(graph)
    assert cycles["count"] >= 1
    hops = two_hop_exposure(graph, seed_account_ids=["A1"])
    assert hops["count"] >= 1


def test_empty_scope_warning(graph_session: Session) -> None:
    graph, warnings = build_relationship_graph(
        graph_session,
        NormalizedFilters(),
        allow_unscoped=False,
    )
    assert graph.number_of_edges() == 0
    assert "EMPTY_GRAPH_SCOPE" in warnings


def test_graph_disabled_skips(tmp_path: Path, graph_session: Session) -> None:
    settings = _settings(tmp_path, graph_enabled=False)
    context = ToolContext(
        session=graph_session,
        policy=load_policy_config(settings.policy_config_path),
        settings=settings,
        filters=NormalizedFilters(customer_ids=["C1"]),
        as_of=AS_OF,
    )
    result = handle_graph_analysis(context, "shared_device", {"customer_id": "C1"})
    assert result.status is ToolStatus.SKIPPED
    assert "GRAPH_DISABLED" in result.warnings


def test_corpus_load_and_retrieval_hits(tmp_path: Path, graph_session: Session) -> None:
    docs = load_corpus(Path("config/policy/corpus/policy_excerpts.v1.json"))
    assert len(docs) >= 3
    assert all("source_url" in doc for doc in docs)
    settings = _settings(tmp_path)
    context = ToolContext(
        session=graph_session,
        policy=load_policy_config(settings.policy_config_path),
        settings=settings,
        filters=NormalizedFilters(),
        as_of=AS_OF,
    )
    result = handle_retrieval(
        context,
        "search_policy",
        {"query": "structuring currency transaction reporting threshold"},
    )
    assert result.status is ToolStatus.SUCCESS
    assert "POLICY_CONTEXT_ONLY" in result.warnings
    assert result.data["count"] >= 1
    hit = result.data["hits"][0]
    assert "doc_id" in hit and "source_url" in hit
    assert "legal_conclusion" not in hit


def test_retrieval_disabled_skips(tmp_path: Path, graph_session: Session) -> None:
    settings = _settings(tmp_path, retrieval_enabled=False)
    context = ToolContext(
        session=graph_session,
        policy=load_policy_config(settings.policy_config_path),
        settings=settings,
        filters=NormalizedFilters(),
        as_of=AS_OF,
    )
    result = handle_retrieval(context, "search_policy", {"query": "aml"})
    assert result.status is ToolStatus.SKIPPED
    assert "RETRIEVAL_DISABLED" in result.warnings


def test_registry_dispatches_phase7_tools(tmp_path: Path, graph_session: Session) -> None:
    from backend.app.tools.graph.queries import connected_accounts
    from backend.app.tools.registry import build_tool_registry

    settings = _settings(tmp_path)
    context = ToolContext(
        session=graph_session,
        policy=load_policy_config(settings.policy_config_path),
        settings=settings,
        filters=NormalizedFilters(customer_ids=["C1", "C2"]),
        as_of=AS_OF,
    )
    registry = build_tool_registry()
    graph_result = registry.dispatch(
        ToolName.GRAPH_ANALYSIS,
        "shared_device",
        context=context,
        parameters={"customer_id": "C1"},
    )
    assert graph_result.status is ToolStatus.SUCCESS
    assert "PHASE_7_NOT_IMPLEMENTED" not in graph_result.warnings
    cycle = registry.dispatch(
        ToolName.GRAPH_ANALYSIS,
        "circular_transfers",
        context=context,
        parameters={},
    )
    assert cycle.status is ToolStatus.SUCCESS
    hops = registry.dispatch(
        ToolName.GRAPH_ANALYSIS,
        "two_hop_exposure",
        context=context,
        parameters={"account_id": "A1"},
    )
    assert hops.status is ToolStatus.SUCCESS
    connected = registry.dispatch(
        ToolName.GRAPH_ANALYSIS,
        "connected_accounts",
        context=context,
        parameters={"account_ids": ["A1"]},
    )
    assert connected.status is ToolStatus.SUCCESS
    graph, _ = build_relationship_graph(graph_session, NormalizedFilters(customer_ids=["C1", "C2"]))
    assert connected_accounts(graph, seed_account_ids=["A1"])["count"] >= 0
    retr = registry.dispatch(
        ToolName.RETRIEVAL,
        "search_policy",
        context=context,
        parameters={"query": "customer due diligence"},
    )
    assert retr.status is ToolStatus.SUCCESS


def test_retrieval_empty_query_and_missing_corpus(tmp_path: Path, graph_session: Session) -> None:
    settings = _settings(tmp_path)
    context = ToolContext(
        session=graph_session,
        policy=load_policy_config(settings.policy_config_path),
        settings=settings,
        filters=NormalizedFilters(),
        as_of=AS_OF,
    )
    empty = handle_retrieval(context, "search_policy", {"query": "  "})
    assert empty.status is ToolStatus.SUCCESS
    assert "EMPTY_QUERY" in empty.warnings
    missing = handle_retrieval(
        ToolContext(
            session=graph_session,
            policy=load_policy_config(settings.policy_config_path),
            settings=_settings(tmp_path, policy_corpus_path=tmp_path / "missing.json"),
            filters=NormalizedFilters(),
            as_of=AS_OF,
        ),
        "search_policy",
        {"query": "aml"},
    )
    assert missing.status is ToolStatus.SKIPPED
    assert "CORPUS_MISSING" in missing.warnings
