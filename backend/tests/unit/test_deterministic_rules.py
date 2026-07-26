"""Boundaries, validation, provenance, and dispatch for deterministic rules."""

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from backend.app.domain.enums import (
    EntityType,
    TransactionDirection,
    ValueType,
)
from backend.app.domain.features import (
    EntityScope,
    FeatureProvenance,
    FeatureRequest,
    FeatureResult,
    FeatureValue,
    FeatureWarning,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.policy.config import PolicyConfig, load_policy_config
from backend.app.rules import (
    RULE_ENGINE,
    RuleEngine,
    RuleInput,
    StructuringRule,
    build_rule_engine,
)

AS_OF = datetime(2026, 7, 1, tzinfo=UTC)
POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))


def _value(name: str, value: object) -> FeatureValue:
    if isinstance(value, bool):
        value_type = ValueType.BOOLEAN
    elif isinstance(value, int):
        value_type = ValueType.INTEGER
    elif isinstance(value, Decimal):
        value_type = ValueType.DECIMAL
    else:
        raise AssertionError(f"unsupported fixture value: {value!r}")
    return FeatureValue(name=name, value_type=value_type, value=value)


def _result(
    operation: str,
    values: dict[str, object],
    *,
    window: timedelta,
    directions: tuple[TransactionDirection, ...] = (),
    countries: tuple[str, ...] = (),
    currency: str | None = "USD",
    warnings: tuple[FeatureWarning, ...] = (),
) -> FeatureResult:
    request = FeatureRequest(
        operation=operation,
        version="v1",
        as_of=AS_OF,
        window=FeatureWindow(
            start_inclusive=AS_OF - window,
            end_exclusive=AS_OF,
        ),
        scope=EntityScope(
            entity_type=EntityType.CUSTOMER,
            entity_ids=("C1",),
        ),
        transaction_filter=TransactionFilter(
            directions=directions,
            countries=countries,
            currency=currency,
        ),
    )
    return FeatureResult(
        request=request,
        values=tuple(_value(name, value) for name, value in values.items()),
        warnings=warnings,
        provenance=FeatureProvenance(
            source=f"fixture:{operation}",
            dataset_version="dataset.v1",
            operation_version="v1",
            policy_version=POLICY.version,
            query_id=f"query:{operation}",
        ),
    )


def _rule_input(
    rule_id: str,
    *,
    overrides: dict[str, object] | None = None,
    countries: tuple[str, ...] | None = None,
    directions: tuple[TransactionDirection, ...] | None = None,
) -> RuleInput:
    fixtures: dict[str, tuple[timedelta, dict[str, object]]] = {
        "structuring.v1": (
            timedelta(days=7),
            {"subthreshold_count": 3},
        ),
        "smurfing.v1": (
            timedelta(hours=48),
            {"transaction_count": 5, "distinct_counterparties": 4},
        ),
        "velocity.v1": (
            timedelta(minutes=120),
            {"rolling_count": 10},
        ),
        "rapid_cash_out.v1": (
            timedelta(minutes=120),
            {"rapid_cash_out_ratio": Decimal("0.80")},
        ),
        "round_numbers.v1": (
            timedelta(days=30),
            {
                "transaction_count": 8,
                "round_number_ratio": Decimal("0.80"),
            },
        ),
        "profile_deviation.v1": (
            timedelta(days=30),
            {
                "data_sufficiency": True,
                "transaction_count": 3,
                "transaction_total": Decimal(500_000),
                "activity_vs_expected": Decimal("3.0"),
            },
        ),
        "high_risk_country.v1": (
            timedelta(days=30),
            {
                "transaction_count": 3,
                "transaction_total": Decimal(500_000),
            },
        ),
    }
    window, values = fixtures[rule_id]
    values.update(overrides or {})
    actual_countries = (
        ("ZZ",) if rule_id == "high_risk_country.v1" and countries is None else countries or ()
    )
    actual_directions = (
        (TransactionDirection.CREDIT,)
        if rule_id == "smurfing.v1" and directions is None
        else directions or ()
    )
    results = tuple(
        _result(
            operation,
            {operation: value},
            window=window,
            countries=actual_countries,
            directions=actual_directions,
        )
        for operation, value in values.items()
    )
    return RuleInput(
        entity_type=EntityType.CUSTOMER,
        entity_id="C1",
        feature_results=results,
    )


@pytest.mark.parametrize(
    ("rule_id", "feature_name", "below"),
    [
        ("structuring.v1", "subthreshold_count", 2),
        ("smurfing.v1", "transaction_count", 4),
        ("smurfing.v1", "distinct_counterparties", 3),
        ("velocity.v1", "rolling_count", 9),
        ("rapid_cash_out.v1", "rapid_cash_out_ratio", Decimal("0.799")),
        ("round_numbers.v1", "transaction_count", 7),
        ("round_numbers.v1", "round_number_ratio", Decimal("0.799")),
        ("profile_deviation.v1", "transaction_count", 2),
        ("profile_deviation.v1", "transaction_total", Decimal(499_999)),
        ("profile_deviation.v1", "activity_vs_expected", Decimal("2.999")),
        ("high_risk_country.v1", "transaction_count", 2),
        ("high_risk_country.v1", "transaction_total", Decimal(499_999)),
    ],
)
def test_rule_thresholds_are_inclusive_at_equality_and_reject_below(
    rule_id: str,
    feature_name: str,
    below: object,
) -> None:
    equal = RULE_ENGINE.dispatch(
        rule_id,
        rule_input=_rule_input(rule_id),
        policy=POLICY,
    )
    lower = RULE_ENGINE.dispatch(
        rule_id,
        rule_input=_rule_input(rule_id, overrides={feature_name: below}),
        policy=POLICY,
    )

    assert equal.fired is True
    assert lower.fired is False
    assert equal.thresholds_used
    assert {value.name for value in equal.features_used} >= {feature_name}


@pytest.mark.parametrize(
    ("rule_id", "feature_name", "above"),
    [
        ("structuring.v1", "subthreshold_count", 4),
        ("smurfing.v1", "transaction_count", 6),
        ("smurfing.v1", "distinct_counterparties", 5),
        ("velocity.v1", "rolling_count", 11),
        ("rapid_cash_out.v1", "rapid_cash_out_ratio", Decimal("0.801")),
        ("round_numbers.v1", "transaction_count", 9),
        ("round_numbers.v1", "round_number_ratio", Decimal("0.801")),
        ("profile_deviation.v1", "transaction_count", 4),
        ("profile_deviation.v1", "transaction_total", Decimal(500_001)),
        ("profile_deviation.v1", "activity_vs_expected", Decimal("3.001")),
        ("high_risk_country.v1", "transaction_count", 4),
        ("high_risk_country.v1", "transaction_total", Decimal(500_001)),
    ],
)
def test_rule_thresholds_fire_above_equality(
    rule_id: str,
    feature_name: str,
    above: object,
) -> None:
    result = RULE_ENGINE.dispatch(
        rule_id,
        rule_input=_rule_input(rule_id, overrides={feature_name: above}),
        policy=POLICY,
    )

    assert result.fired is True


def test_missing_invalid_and_warned_features_return_deterministic_reasons() -> None:
    missing = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(),
        ),
        policy=POLICY,
    )
    invalid_result = _result(
        "subthreshold_count",
        {},
        window=timedelta(days=7),
    )
    invalid = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(invalid_result,),
        ),
        policy=POLICY,
    )
    warned_result = _result(
        "subthreshold_count",
        {"subthreshold_count": 10},
        window=timedelta(days=7),
        warnings=(FeatureWarning(code="QUERY_LIMIT_REACHED", message="bounded result"),),
    )
    warned = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(warned_result,),
        ),
        policy=POLICY,
    )

    assert (missing.fired, missing.reason_code) == (False, "MISSING_REQUIRED_FEATURES")
    assert (invalid.fired, invalid.reason_code) == (
        False,
        "MISSING_REQUIRED_FEATURE_VALUE",
    )
    assert (warned.fired, warned.reason_code) == (False, "FEATURE_DATA_WARNINGS")


def test_invalid_semantic_value_and_policy_mismatch_do_not_fire() -> None:
    negative = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=_rule_input(
            "structuring.v1",
            overrides={"subthreshold_count": -1},
        ),
        policy=POLICY,
    )
    feature = _rule_input("structuring.v1").feature_results[0]
    wrong_policy = feature.model_copy(
        update={
            "provenance": feature.provenance.model_copy(
                update={"policy_version": "reporting_thresholds.other"}
            )
        }
    )
    stale = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(wrong_policy,),
        ),
        policy=POLICY,
    )

    assert (negative.fired, negative.reason_code) == (False, "INVALID_FEATURE_VALUE")
    assert (stale.fired, stale.reason_code) == (False, "FEATURE_POLICY_MISMATCH")


def test_profile_input_has_no_pep_kyc_or_residence_and_pep_only_cannot_fire() -> None:
    assert {item.name for item in fields(RuleInput)} == {
        "entity_type",
        "entity_id",
        "feature_results",
    }
    result = RULE_ENGINE.dispatch(
        "profile_deviation.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(),
        ),
        policy=POLICY,
    )
    assert result.fired is False


def test_country_and_smurfing_rules_reject_unscoped_aggregates() -> None:
    country = RULE_ENGINE.dispatch(
        "high_risk_country.v1",
        rule_input=_rule_input("high_risk_country.v1", countries=("US",)),
        policy=POLICY,
    )
    smurfing = RULE_ENGINE.dispatch(
        "smurfing.v1",
        rule_input=_rule_input("smurfing.v1", directions=()),
        policy=POLICY,
    )

    assert country.reason_code == "HIGH_RISK_COUNTRY_SCOPE_REQUIRED"
    assert smurfing.reason_code == "INBOUND_TRANSACTION_SCOPE_REQUIRED"
    assert not country.fired
    assert not smurfing.fired


def test_evidence_refs_and_features_are_copied_from_feature_results() -> None:
    rule_input = _rule_input("round_numbers.v1")
    result = RULE_ENGINE.dispatch(
        "round_numbers.v1",
        rule_input=rule_input,
        policy=POLICY,
    )

    assert result.features_used == tuple(item.values[0] for item in rule_input.feature_results)
    assert result.evidence_refs == tuple(
        item.provenance.query_id for item in rule_input.feature_results
    )


def test_engine_guards_duplicates_and_evaluates_in_stable_order() -> None:
    engine = RuleEngine()
    engine.register(StructuringRule())
    with pytest.raises(ValueError, match="already registered"):
        engine.register(StructuringRule())

    full_engine = build_rule_engine()
    results = full_engine.evaluate_many(
        rule_inputs={
            "velocity.v1": _rule_input("velocity.v1"),
            "structuring.v1": _rule_input("structuring.v1"),
        },
        policy=POLICY,
        rule_ids=("velocity.v1", "structuring.v1"),
    )
    assert tuple(item.rule_id for item in results) == (
        "structuring.v1",
        "velocity.v1",
    )
    with pytest.raises(ValueError, match="cannot contain duplicates"):
        full_engine.evaluate_many(
            rule_inputs={"structuring.v1": _rule_input("structuring.v1")},
            policy=POLICY,
            rule_ids=("structuring.v1", "structuring.v1"),
        )
    with pytest.raises(ValueError, match="missing rule inputs"):
        full_engine.evaluate_many(
            rule_inputs={"structuring.v1": _rule_input("structuring.v1")},
            policy=POLICY,
            rule_ids=("structuring.v1", "velocity.v1"),
        )


def test_rule_package_has_no_database_or_sqlalchemy_imports() -> None:
    rules_root = Path("backend/app/rules")
    source = "\n".join(path.read_text(encoding="utf-8") for path in rules_root.rglob("*.py"))
    forbidden = (
        "sqlalchemy",
        "backend.app.data.models",
        "backend.app.data.repositories",
        "backend.app.data.database",
    )
    assert not any(name in source for name in forbidden)


def test_policy_type_is_shared_without_rule_local_configuration() -> None:
    assert isinstance(POLICY, PolicyConfig)
