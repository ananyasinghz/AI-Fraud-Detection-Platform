"""Hand-calculated integration coverage for every Phase 2 feature operation."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine

from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import (
    Account,
    Base,
    Counterparty,
    Customer,
    CustomerProfile,
    DatasetRun,
    Device,
    Transaction,
)
from backend.app.data.query_scope import QueryScope
from backend.app.domain.enums import EntityType, TransactionDirection
from backend.app.domain.features import (
    EntityScope,
    FeatureRequest,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.domain.filters import NormalizedFilters
from backend.app.policy.config import load_policy_config
from backend.app.rules import RULE_ENGINE, RuleInput
from backend.app.tools.features.registry import FEATURE_REGISTRY, UnknownFeatureOperationError

START = datetime(2026, 1, 1, tzinfo=UTC)
END = START + timedelta(days=60)
POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))


def _transaction(
    transaction_id: str,
    occurred_at: datetime,
    amount_minor: int,
    *,
    customer_id: str = "C1",
    account_id: str = "A1",
    currency: str = "USD",
    direction: str = "credit",
    transaction_type: str = "cash_deposit",
    country: str = "US",
    counterparty_id: str | None = "CP1",
    device_id: str | None = "D1",
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        customer_id=customer_id,
        account_id=account_id,
        occurred_at=occurred_at,
        amount_minor=amount_minor,
        currency=currency,
        direction=direction,
        transaction_type=transaction_type,
        channel="branch",
        country=country,
        counterparty_id=counterparty_id,
        device_id=device_id,
        ml_eligible=False,
        data_source="synthetic",
        seed_run_id="feature-fixture-v1",
    )


def _seed(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        session.add(
            DatasetRun(
                run_id="feature-fixture-v1",
                run_kind="aml_seed",
                alembic_revision="head",
                record_counts={},
                created_at=START,
            )
        )
        session.add_all(
            [
                Customer(customer_id="C1", created_at=START, status="active"),
                Customer(customer_id="C2", created_at=START, status="active"),
                Counterparty(counterparty_id="CP1", display_name="One"),
                Counterparty(counterparty_id="CP2", display_name="Two"),
                Device(
                    device_id="D1",
                    device_type="browser",
                    first_seen_at=START,
                    last_seen_at=END,
                ),
                Device(
                    device_id="D2",
                    device_type="mobile",
                    first_seen_at=START,
                    last_seen_at=END,
                ),
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
                    opened_at=START - timedelta(days=10),
                    status="active",
                ),
                Account(
                    account_id="A2",
                    customer_id="C2",
                    account_type="checking",
                    currency="EUR",
                    country="DE",
                    opened_at=START,
                    status="active",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                CustomerProfile(
                    customer_id="C1",
                    segment="retail",
                    residence_country="US",
                    occupation_or_industry="engineer",
                    declared_annual_income_minor=18_250_000,
                    income_currency="USD",
                    expected_monthly_volume_min_minor=1_000_000,
                    expected_monthly_volume_max_minor=2_000_000,
                    volume_currency="USD",
                    kyc_risk_rating="low",
                    pep_flag=False,
                    profile_effective_from=START - timedelta(days=1),
                    profile_effective_to=START + timedelta(days=40),
                    profile_source="fixture",
                ),
                CustomerProfile(
                    customer_id="C1",
                    segment="retail",
                    residence_country="US",
                    occupation_or_industry="engineer",
                    declared_annual_income_minor=36_500_000,
                    income_currency="USD",
                    expected_monthly_volume_min_minor=3_000_000,
                    expected_monthly_volume_max_minor=6_000_000,
                    volume_currency="USD",
                    kyc_risk_rating="low",
                    pep_flag=False,
                    profile_effective_from=START + timedelta(days=40),
                    profile_source="fixture",
                ),
                CustomerProfile(
                    customer_id="C2",
                    segment="retail",
                    residence_country="DE",
                    pep_flag=False,
                    profile_effective_from=START,
                    profile_source="fixture",
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                _transaction("T1", START + timedelta(days=1), 700_000),
                _transaction(
                    "T2",
                    START + timedelta(days=2),
                    990_000,
                    country="GB",
                    counterparty_id="CP2",
                    device_id="D2",
                ),
                _transaction(
                    "T3",
                    START + timedelta(days=3),
                    1_000_000,
                    counterparty_id=None,
                    device_id=None,
                ),
                _transaction(
                    "T4",
                    START + timedelta(days=31),
                    500_000,
                    transaction_type="wire",
                ),
                _transaction(
                    "T5",
                    START + timedelta(days=31, hours=2),
                    400_000,
                    direction="debit",
                    transaction_type="cash_withdrawal",
                ),
                _transaction("T-end", END, 9_999_999),
                _transaction(
                    "T-eur",
                    START + timedelta(days=1),
                    100_000,
                    customer_id="C2",
                    account_id="A2",
                    currency="EUR",
                    country="DE",
                ),
            ]
        )


@pytest.fixture
def feature_engine(tmp_path: Path) -> Iterator[Engine]:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'features.db').as_posix()}")
    _seed(engine)
    yield engine
    engine.dispose()


def _request(operation: str, *, customer_id: str = "C1", currency: str = "USD") -> FeatureRequest:
    return FeatureRequest(
        operation=operation,
        version="v1",
        as_of=END,
        window=FeatureWindow(start_inclusive=START, end_exclusive=END),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=(customer_id,)),
        transaction_filter=TransactionFilter(currency=currency),
    )


def _scope(request: FeatureRequest) -> QueryScope:
    return QueryScope.from_feature_request(
        NormalizedFilters(
            date_from=START,
            date_to=END,
            customer_ids=list(request.scope.entity_ids),
            currency=request.transaction_filter.currency,
            max_results=100,
        ),
        request,
    )


def _values(result: object) -> dict[str, object]:
    assert hasattr(result, "values")
    return {item.name: item.value for item in result.values}


EXPECTED_PRIMARY: dict[str, object] = {
    "transaction_count": 5,
    "transaction_total": Decimal(3_590_000),
    "rolling_count": 5,
    "rolling_sum": Decimal(3_590_000),
    "average_amount": Decimal(718_000),
    "median_amount": Decimal(700_000),
    "maximum_amount": Decimal(1_000_000),
    "amount_deviation": Decimal("245959.3462342913286675993465"),
    "period_baseline_deviation": Decimal(-1_790_000),
    "transactions_per_hour": Decimal(5) / Decimal(1440),
    "transactions_per_day": Decimal(1) / Decimal(12),
    "cash_deposit_count": 3,
    "cash_deposit_sum": Decimal(2_690_000),
    "subthreshold_count": 2,
    "subthreshold_total": Decimal(1_690_000),
    "round_number_ratio": Decimal(4) / Decimal(5),
    "rapid_cash_out_ratio": Decimal(400_000) / Decimal(3_190_000),
    "rapid_cash_out_elapsed_time": Decimal(120),
    "distinct_counterparties": 2,
    "distinct_accounts": 1,
    "distinct_devices": 2,
    "distinct_countries": 2,
    "activity_vs_expected": Decimal(3_590_000) / Decimal(12_000_000),
    "income_to_volume_ratio": Decimal(3_590_000) / Decimal(6_000_000),
    "account_tenure_days": 70,
    "profile_completeness": Decimal(1),
    "data_sufficiency": False,
}


@pytest.mark.parametrize("operation, expected", EXPECTED_PRIMARY.items())
def test_every_registered_operation_has_hand_calculated_output(
    feature_engine: Engine,
    operation: str,
    expected: object,
) -> None:
    factory = session_factory(feature_engine)
    request = _request(operation)
    with session_scope(factory) as session:
        result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=_scope(request),
        )

    value = _values(result)[operation]
    if isinstance(expected, Decimal):
        assert isinstance(value, Decimal)
        assert value == pytest.approx(expected)
    else:
        assert value == expected
    assert result.denominators
    assert result.provenance.query_id
    assert result.provenance.source.startswith("transactions:")


def test_boundary_time_thresholds_and_rapid_window_are_half_open(
    feature_engine: Engine,
) -> None:
    factory = session_factory(feature_engine)
    with session_scope(factory) as session:
        count_request = _request("transaction_count")
        count_result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=count_request,
            scope=_scope(count_request),
        )
        threshold_request = _request("subthreshold_count")
        threshold_result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=threshold_request,
            scope=_scope(threshold_request),
        )
        elapsed_request = _request("rapid_cash_out_elapsed_time")
        elapsed_result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=elapsed_request,
            scope=_scope(elapsed_request),
        )

    assert _values(count_result)["transaction_count"] == 5  # T-end is excluded.
    assert _values(threshold_result)["subthreshold_count"] == 2  # Exact threshold excluded.
    assert _values(elapsed_result)["rapid_cash_out_elapsed_time"] == Decimal(120)


def test_empty_scope_and_missing_profile_are_valid_warning_results(
    feature_engine: Engine,
) -> None:
    factory = session_factory(feature_engine)
    request = _request("activity_vs_expected", customer_id="missing")
    scope = QueryScope.empty(reason="fixture has no matching customer", as_of=END)
    with session_scope(factory) as session:
        result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=scope,
        )

    assert _values(result)["activity_vs_expected"] is None
    assert {"EMPTY_SCOPE", "PROFILE_NOT_FOUND"} <= {item.code for item in result.warnings}


def test_policy_currency_mismatch_returns_warning_not_converted_money(
    feature_engine: Engine,
) -> None:
    factory = session_factory(feature_engine)
    request = _request("subthreshold_total", customer_id="C2", currency="EUR")
    with session_scope(factory) as session:
        result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=_scope(request),
        )

    assert _values(result)["subthreshold_total"] is None
    assert "POLICY_CURRENCY_MISMATCH" in {item.code for item in result.warnings}


def test_profile_operation_uses_profile_effective_at_as_of(feature_engine: Engine) -> None:
    early_end = START + timedelta(days=30)
    request = FeatureRequest(
        operation="activity_vs_expected",
        version="v1",
        as_of=early_end,
        window=FeatureWindow(start_inclusive=START, end_exclusive=early_end),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C1",)),
        transaction_filter=TransactionFilter(currency="USD"),
    )
    scope = QueryScope.from_feature_request(
        NormalizedFilters(
            date_from=START,
            date_to=early_end,
            customer_ids=["C1"],
            currency="USD",
        ),
        request,
    )
    factory = session_factory(feature_engine)
    with session_scope(factory) as session:
        result = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=scope,
        )

    assert _values(result)["expected_activity_max"] == Decimal(2_000_000)
    assert _values(result)["activity_vs_expected"] == Decimal(2_690_000) / Decimal(2_000_000)


def test_repeated_dispatch_and_direct_registry_call_are_deterministic(
    feature_engine: Engine,
) -> None:
    factory = session_factory(feature_engine)
    request = _request("transaction_total")
    scope = _scope(request)
    with session_scope(factory) as session:
        first = FEATURE_REGISTRY.dispatch(
            session=session,
            policy=POLICY,
            request=request,
            scope=scope,
        )
        second = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=scope,
        )
    assert first == second
    assert len(FEATURE_REGISTRY.registered()) == len(EXPECTED_PRIMARY)


def test_registry_rejects_unknown_versions_and_scope_widening(feature_engine: Engine) -> None:
    factory = session_factory(feature_engine)
    unknown = _request("transaction_count").model_copy(update={"version": "v2"})
    with session_scope(factory) as session:
        with pytest.raises(UnknownFeatureOperationError):
            FEATURE_REGISTRY(
                session=session,
                policy=POLICY,
                request=unknown,
                scope=_scope(unknown),
            )

        request = _request("transaction_count")
        widened = QueryScope.from_feature_request(
            NormalizedFilters(date_from=START, date_to=END, customer_ids=["C2"]),
            _request("transaction_count", customer_id="C2"),
        )
        with pytest.raises(ValueError, match="entity scope"):
            FEATURE_REGISTRY(
                session=session,
                policy=POLICY,
                request=request,
                scope=widened,
            )


def test_structuring_rule_consumes_direct_registry_output(feature_engine: Engine) -> None:
    end = START + timedelta(days=7)
    request = FeatureRequest(
        operation="subthreshold_count",
        version="v1",
        as_of=end,
        window=FeatureWindow(start_inclusive=START, end_exclusive=end),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C1",)),
        transaction_filter=TransactionFilter(currency="USD"),
    )
    scope = QueryScope.from_feature_request(
        NormalizedFilters(
            date_from=START,
            date_to=end,
            customer_ids=["C1"],
            currency="USD",
        ),
        request,
    )
    factory = session_factory(feature_engine)
    with session_scope(factory) as session:
        feature = FEATURE_REGISTRY(
            session=session,
            policy=POLICY,
            request=request,
            scope=scope,
        )

    rule = RULE_ENGINE.dispatch(
        "structuring.v1",
        rule_input=RuleInput(
            entity_type=EntityType.CUSTOMER,
            entity_id="C1",
            feature_results=(feature,),
        ),
        policy=POLICY,
    )

    assert rule.features_used == (feature.values[0],)
    assert rule.evidence_refs == (feature.provenance.query_id,)
    assert rule.fired is False
    assert rule.reason_code == "SUB_THRESHOLD_COUNT_BELOW_MINIMUM"


@pytest.mark.parametrize(
    ("rule_id", "operations", "window", "end", "directions", "countries"),
    [
        (
            "structuring.v1",
            ("subthreshold_count",),
            timedelta(days=7),
            START + timedelta(days=7),
            (),
            (),
        ),
        (
            "smurfing.v1",
            ("transaction_count", "distinct_counterparties"),
            timedelta(hours=48),
            START + timedelta(days=32),
            (TransactionDirection.CREDIT,),
            (),
        ),
        (
            "velocity.v1",
            ("rolling_count",),
            timedelta(minutes=120),
            START + timedelta(days=31, hours=2, seconds=1),
            (),
            (),
        ),
        (
            "rapid_cash_out.v1",
            ("rapid_cash_out_ratio",),
            timedelta(minutes=120),
            START + timedelta(days=31, hours=2),
            (),
            (),
        ),
        (
            "round_numbers.v1",
            ("transaction_count", "round_number_ratio"),
            timedelta(days=30),
            START + timedelta(days=32),
            (),
            (),
        ),
        (
            "profile_deviation.v1",
            (
                "data_sufficiency",
                "transaction_count",
                "transaction_total",
                "activity_vs_expected",
            ),
            timedelta(days=30),
            START + timedelta(days=32),
            (),
            (),
        ),
        (
            "high_risk_country.v1",
            ("transaction_count", "transaction_total"),
            timedelta(days=30),
            START + timedelta(days=32),
            (),
            ("ZZ",),
        ),
    ],
)
def test_each_rule_consumes_unmodified_direct_feature_results(
    feature_engine: Engine,
    rule_id: str,
    operations: tuple[str, ...],
    window: timedelta,
    end: datetime,
    directions: tuple[TransactionDirection, ...],
    countries: tuple[str, ...],
) -> None:
    factory = session_factory(feature_engine)
    features = []
    with session_scope(factory) as session:
        if rule_id == "rapid_cash_out.v1":
            session.add(
                _transaction(
                    "T-rule-cash-out",
                    START + timedelta(days=31, hours=1),
                    400_000,
                    direction="debit",
                    transaction_type="cash_withdrawal",
                )
            )
            session.flush()
        for operation in operations:
            request = FeatureRequest(
                operation=operation,
                version="v1",
                as_of=end,
                window=FeatureWindow(
                    start_inclusive=end - window,
                    end_exclusive=end,
                ),
                scope=EntityScope(
                    entity_type=EntityType.CUSTOMER,
                    entity_ids=("C1",),
                ),
                transaction_filter=TransactionFilter(
                    directions=directions,
                    countries=countries,
                    currency="USD",
                ),
            )
            features.append(
                FEATURE_REGISTRY(
                    session=session,
                    policy=POLICY,
                    request=request,
                    scope=_scope(request),
                )
            )

    rule_input = RuleInput(
        entity_type=EntityType.CUSTOMER,
        entity_id="C1",
        feature_results=tuple(features),
    )
    result = RULE_ENGINE.dispatch(
        rule_id,
        rule_input=rule_input,
        policy=POLICY,
    )

    assert result.features_used == tuple(
        next(value for value in feature.values if value.name == feature.request.operation)
        for feature in features
    )
    assert result.evidence_refs == tuple(feature.provenance.query_id for feature in features)
