"""Synthetic scenario boundary and database integration tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import pytest
from sqlalchemy import func, select, text

from backend.app.data.database import (
    create_database_engine,
    session_factory,
    session_scope,
)
from backend.app.data.models import Base, DatasetRun, Transaction
from backend.app.data.repositories import CustomerRepository, TransactionRepository
from backend.app.generation import generate_scenarios
from backend.app.generation.contracts import GenerationResult
from backend.app.generation.io import read_runtime_bundle, write_runtime_bundle
from backend.app.generation.seeder import seed_runtime_bundle
from backend.evaluation.scenario_manifest import (
    build_manifest,
    read_manifest,
    write_manifest,
)

GENERATION_CONFIG = Path("config/generation/scenario_catalog.v1.yaml")
POLICY_CONFIG = Path("config/policy/reporting_thresholds.v1.yaml")


def _generate(
    seed: int = 42,
    split: Literal["dev", "held_out", "ci_tiny"] = "dev",
) -> GenerationResult:
    return generate_scenarios(
        seed=seed,
        split=split,
        generation_config_path=GENERATION_CONFIG,
        policy_config_path=POLICY_CONFIG,
    )


def test_generation_is_deterministic_separated_and_complete(tmp_path: Path) -> None:
    first = _generate()
    repeated = _generate()
    held_out = _generate(seed=99, split="held_out")
    assert first.runtime.fingerprint == repeated.runtime.fingerprint
    assert held_out.runtime.fingerprint != first.runtime.fingerprint

    patterns = {annotation.pattern_type for annotation in first.annotations}
    assert {
        "clean_control",
        "structuring",
        "smurfing",
        "velocity",
        "rapid_cash_out",
        "round_number",
        "spending_increase",
        "profile_deviation",
        "new_account",
        "high_risk_country",
        "graph_relationship",
    } == patterns
    control_targets = {
        signal.removeprefix("control_for_")
        for annotation in first.annotations
        if annotation.pattern_type == "clean_control"
        for signal in annotation.expected_signals
        if signal.startswith("control_for_")
    }
    assert control_targets == patterns - {"clean_control", "graph_relationship"}
    assert all(type(item.amount_minor) is int for item in first.runtime.transactions)
    assert all(not item.ml_eligible for item in first.runtime.transactions)

    runtime_json = first.runtime.model_dump_json()
    for forbidden in (
        "scenario_label",
        "is_suspicious",
        "injected_pattern",
        "expected_signals",
    ):
        assert forbidden not in runtime_json

    runtime_path = tmp_path / "runtime.json"
    manifest_path = tmp_path / "hidden" / "manifest.json"
    write_runtime_bundle(first.runtime, runtime_path)
    write_manifest(build_manifest(first), manifest_path)
    assert read_runtime_bundle(runtime_path) == first.runtime
    assert read_manifest(manifest_path).runtime_fingerprint == first.runtime.fingerprint


def test_seed_is_idempotent_and_histories_are_queryable(tmp_path: Path) -> None:
    result = _generate()
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = session_factory(engine)

    with session_scope(factory) as session:
        created = seed_runtime_bundle(session, result.runtime)
        assert created.created is True
    with session_scope(factory) as session:
        repeated = seed_runtime_bundle(session, result.runtime)
        assert repeated.created is False
        assert session.scalar(select(func.count()).select_from(DatasetRun)) == 1
        assert session.scalar(select(func.count()).select_from(Transaction)) == len(
            result.runtime.transactions
        )
        assert session.scalar(text("PRAGMA foreign_key_check")) is None

        customer_repository = CustomerRepository(session)
        transaction_repository = TransactionRepository(session)
        as_of = datetime(2026, 7, 25, tzinfo=UTC)
        for customer_id in (
            "cus-dev-42-clean-000",
            "cus-dev-42-structuring-00",
        ):
            profile = customer_repository.get_profile_as_of(customer_id, as_of)
            assert profile.profile is not None
            transactions = transaction_repository.list_for_customer(
                customer_id,
                date_from=as_of - timedelta(days=365),
                date_to=as_of,
            )
            assert transactions
            assert all(
                transaction.seed_run_id == result.runtime.run_id for transaction in transactions
            )

    changed = result.runtime.model_copy(update={"fingerprint": "0" * 64})
    with (
        pytest.raises(ValueError, match="different fingerprint"),
        session_scope(factory) as session,
    ):
        seed_runtime_bundle(session, changed)
    engine.dispose()


def test_runtime_package_cannot_import_evaluation_manifest() -> None:
    for path in Path("backend/app").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "backend.evaluation" not in source
        assert "scenario_manifest" not in source
