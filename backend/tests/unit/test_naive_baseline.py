"""Tests for the evaluation-only fixed-threshold benchmark."""

import ast
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.generation.contracts import RuntimeBundle, TransactionSeed
from backend.evaluation.naive_baseline import (
    NaiveBaselineConfig,
    ThresholdProvenance,
    apply_naive_baseline,
    load_naive_baseline_config,
)

CONFIG_PATH = Path("config/evaluation/naive_baseline.v1.yaml")


def _config(
    *,
    amount_threshold_minor: int = 1_000,
    transactions_per_day_threshold: int = 3,
) -> NaiveBaselineConfig:
    return NaiveBaselineConfig(
        version="naive_baseline.v1",
        jurisdiction="US",
        currency="USD",
        amount_threshold_minor=amount_threshold_minor,
        transactions_per_day_threshold=transactions_per_day_threshold,
        utc_day_semantics="occurred_at_utc_calendar_day",
        amount_currency_handling="configured_currency_only_without_fx",
        daily_count_currency_scope="all_currencies",
        provenance=ThresholdProvenance(
            selection_data="development_scenarios",
            frozen_before_evaluation=True,
            method="fixed_expert_benchmark",
            notes="Selected on development scenarios and frozen before held-out evaluation.",
        ),
    )


def _transaction(
    transaction_id: str,
    *,
    amount_minor: int,
    occurred_at: datetime,
    currency: str = "USD",
    customer_id: str = "customer-1",
) -> TransactionSeed:
    return TransactionSeed(
        transaction_id=transaction_id,
        account_id=f"account-{customer_id}",
        customer_id=customer_id,
        occurred_at=occurred_at,
        amount_minor=amount_minor,
        currency=currency,
        direction="debit",
        transaction_type="card_purchase",
        channel="online",
    )


def test_fixed_thresholds_cover_below_equal_and_above() -> None:
    moment = datetime(2026, 7, 25, 12, tzinfo=UTC)
    transactions = [
        _transaction("below", amount_minor=999, occurred_at=moment),
        _transaction("equal", amount_minor=1_000, occurred_at=moment + timedelta(minutes=1)),
        _transaction("above", amount_minor=1_001, occurred_at=moment + timedelta(minutes=2)),
    ]

    result = apply_naive_baseline(transactions, _config())

    assert [flag.transaction_id for flag in result.amount_flags] == ["equal", "above"]
    assert len(result.daily_count_flags) == 1
    daily_flag = result.daily_count_flags[0]
    assert daily_flag.transaction_count == 3
    assert daily_flag.transaction_ids == ("above", "below", "equal")


def test_result_is_deterministic_for_input_order_and_runtime_bundle() -> None:
    moment = datetime(2026, 7, 25, 12, tzinfo=UTC)
    transactions = [
        _transaction("b", amount_minor=2_000, occurred_at=moment + timedelta(minutes=1)),
        _transaction("a", amount_minor=2_000, occurred_at=moment),
    ]
    config = _config(transactions_per_day_threshold=2)
    expected = apply_naive_baseline(transactions, config)
    repeated = apply_naive_baseline(list(reversed(transactions)), config)
    assert expected.model_dump_json() == repeated.model_dump_json()

    runtime = RuntimeBundle(
        run_id="run-1",
        seed=1,
        split="held_out",
        generator_version="generator.v1",
        policy_version="policy.v1",
        generated_at=moment,
        customers=[],
        profiles=[],
        accounts=[],
        counterparties=[],
        devices=[],
        transactions=transactions,
        fingerprint="f" * 64,
    )
    runtime_result = apply_naive_baseline(runtime, config)
    assert runtime_result.amount_flags == expected.amount_flags
    assert runtime_result.source_run_id == "run-1"
    assert runtime_result.source_fingerprint == "f" * 64


def test_daily_groups_use_utc_calendar_boundaries() -> None:
    plus_two = timezone(timedelta(hours=2))
    transactions = [
        _transaction(
            "previous-utc-day",
            amount_minor=1,
            occurred_at=datetime(2026, 7, 26, 1, 30, tzinfo=plus_two),
        ),
        _transaction(
            "new-utc-day-1",
            amount_minor=1,
            occurred_at=datetime(2026, 7, 26, 0, 15, tzinfo=UTC),
        ),
        _transaction(
            "new-utc-day-2",
            amount_minor=1,
            occurred_at=datetime(2026, 7, 26, 23, 59, tzinfo=UTC),
        ),
    ]

    result = apply_naive_baseline(
        transactions,
        _config(transactions_per_day_threshold=2),
    )

    assert len(result.daily_count_flags) == 1
    assert result.daily_count_flags[0].utc_day.isoformat() == "2026-07-26"
    assert result.daily_count_flags[0].transaction_ids == (
        "new-utc-day-1",
        "new-utc-day-2",
    )


def test_mixed_currencies_skip_amount_comparison_but_count_velocity() -> None:
    moment = datetime(2026, 7, 25, 12, tzinfo=UTC)
    transactions = [
        _transaction("usd", amount_minor=1_000, occurred_at=moment),
        _transaction(
            "eur",
            amount_minor=50_000,
            occurred_at=moment + timedelta(minutes=1),
            currency="EUR",
        ),
    ]

    result = apply_naive_baseline(
        transactions,
        _config(transactions_per_day_threshold=2),
    )

    assert [flag.transaction_id for flag in result.amount_flags] == ["usd"]
    assert result.daily_count_flags[0].transaction_count == 2
    assert len(result.warnings) == 1
    assert result.warnings[0].currency == "EUR"
    assert "no FX conversion" in result.warnings[0].message


def test_contracts_are_strict_immutable_and_config_has_frozen_provenance() -> None:
    config = load_naive_baseline_config(CONFIG_PATH)
    assert config.provenance.selection_data == "development_scenarios"
    assert config.provenance.frozen_before_evaluation is True

    with pytest.raises(ValidationError):
        NaiveBaselineConfig.model_validate(
            {**config.model_dump(), "amount_threshold_minor": "1000000"}
        )
    with pytest.raises(ValidationError):
        config.amount_threshold_minor = 1


def test_result_serialization_contains_no_labels_or_alerts() -> None:
    transaction = _transaction(
        "transaction-1",
        amount_minor=1_000,
        occurred_at=datetime(2026, 7, 25, tzinfo=UTC),
    )
    payload = json.loads(apply_naive_baseline([transaction], _config()).model_dump_json())
    serialized = json.dumps(payload, sort_keys=True).lower()

    for forbidden in (
        "label",
        "annotation",
        "expected_signal",
        "scenario",
        "is_suspicious",
        "alert",
    ):
        assert forbidden not in serialized


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_runtime_and_benchmark_import_boundaries_are_isolated() -> None:
    for path in Path("backend/app").rglob("*.py"):
        assert not any(
            module == "backend.evaluation" or module.startswith("backend.evaluation.")
            for module in _imported_modules(path)
        )

    benchmark_path = Path("backend/evaluation/naive_baseline.py")
    benchmark_source = benchmark_path.read_text(encoding="utf-8")
    benchmark_imports = _imported_modules(benchmark_path)
    assert "backend.evaluation.scenario_manifest" not in benchmark_imports
    assert "EvaluationManifest" not in benchmark_source
    assert "ScenarioAnnotation" not in benchmark_source
    assert "read_manifest" not in benchmark_source

    benchmark_tree = ast.parse(benchmark_source)
    application = next(
        node
        for node in benchmark_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "apply_naive_baseline"
    )
    file_read_calls = {
        node.func.attr
        for node in ast.walk(application)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"open", "read_bytes", "read_text"}
    }
    assert not file_read_calls
