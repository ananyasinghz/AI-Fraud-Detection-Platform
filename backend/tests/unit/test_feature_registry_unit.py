"""Unit tests for named and versioned feature registration."""

import pytest

from backend.app.tools.features.operations.common import OperationContext, OperationOutput
from backend.app.tools.features.registry import FeatureRegistry, build_feature_registry

EXPECTED_OPERATIONS = {
    "account_tenure_days",
    "activity_vs_expected",
    "amount_deviation",
    "average_amount",
    "cash_deposit_count",
    "cash_deposit_sum",
    "data_sufficiency",
    "distinct_accounts",
    "distinct_countries",
    "distinct_counterparties",
    "distinct_devices",
    "income_to_volume_ratio",
    "maximum_amount",
    "median_amount",
    "period_baseline_deviation",
    "profile_completeness",
    "rapid_cash_out_elapsed_time",
    "rapid_cash_out_ratio",
    "rolling_count",
    "rolling_sum",
    "round_number_ratio",
    "subthreshold_count",
    "subthreshold_total",
    "transaction_count",
    "transaction_total",
    "transactions_per_day",
    "transactions_per_hour",
}


def _empty_operation(context: OperationContext) -> OperationOutput:
    del context
    return OperationOutput(values=())


def test_default_registry_exposes_exact_phase_two_catalog() -> None:
    assert build_feature_registry().registered() == tuple(
        (name, "v1") for name in sorted(EXPECTED_OPERATIONS)
    )


def test_registry_rejects_duplicate_name_and_version_only() -> None:
    registry = FeatureRegistry()
    registry.register("example", "v1", _empty_operation)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("example", "v1", _empty_operation)

    registry.register("example", "v2", _empty_operation)
    assert registry.registered() == (("example", "v1"), ("example", "v2"))
