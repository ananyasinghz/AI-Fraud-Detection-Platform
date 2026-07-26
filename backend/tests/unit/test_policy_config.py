"""Focused tests for shared detection policy configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.generation.config import (
    PolicyConfig as GenerationPolicyConfig,
)
from backend.app.generation.config import (
    load_policy_config as load_generation_policy_config,
)
from backend.app.policy.config import PolicyConfig, load_policy_config

POLICY_PATH = Path("config/policy/reporting_thresholds.v1.yaml")


def test_shared_policy_loader_covers_each_detection_family() -> None:
    policy = load_policy_config(POLICY_PATH)

    assert policy.version == "reporting_thresholds.v1"
    assert policy.jurisdiction == "DEMO-US"
    assert policy.currency == "USD"
    assert policy.structuring.version == "structuring.v1"
    assert policy.smurfing.minimum_distinct_senders == 4
    assert policy.velocity.window_minutes == 120
    assert policy.rapid_cash_out.minimum_cash_out_ratio == 0.8
    assert policy.round_numbers.rounding_increment_minor == 100_000
    assert policy.profile_deviation.minimum_expected_volume_ratio == 3.0
    assert policy.high_risk_country.minimum_transaction_count == 3
    assert policy.high_risk_countries == ("ZZ",)
    assert policy.data_sufficiency.minimum_baseline_transactions == 6


def test_generation_policy_imports_remain_compatible() -> None:
    assert GenerationPolicyConfig is PolicyConfig
    assert load_generation_policy_config(POLICY_PATH) == load_policy_config(POLICY_PATH)


def test_policy_is_frozen_and_validates_threshold_relationships() -> None:
    policy = load_policy_config(POLICY_PATH)

    with pytest.raises(ValidationError, match="frozen"):
        policy.currency = "EUR"

    payload = policy.model_dump()
    payload["structuring"]["lower_bound_ratio"] = 0.99
    payload["structuring"]["upper_bound_ratio"] = 0.70
    with pytest.raises(ValidationError, match="lower_bound_ratio"):
        PolicyConfig.model_validate(payload)
