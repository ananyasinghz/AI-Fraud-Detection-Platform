"""Query-scope resolution tests."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.app.data.query_scope import QueryScope, amount_to_minor
from backend.app.domain.enums import EntityType, PatternType
from backend.app.domain.features import (
    EntityScope,
    FeatureRequest,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.domain.filters import NormalizedFilters


def test_scope_normalizes_utc_and_preserves_half_open_bounds() -> None:
    eastern = timezone(timedelta(hours=-5))
    filters = NormalizedFilters(
        date_from=datetime(2026, 1, 1, tzinfo=eastern),
        date_to=datetime(2026, 1, 2, tzinfo=eastern),
        max_results=25,
    )

    scope = QueryScope.from_filters(filters, limit=50, page=3)

    assert scope.start_inclusive == datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert scope.end_exclusive == datetime(2026, 1, 2, 5, tzinfo=UTC)
    assert scope.limit == 25
    assert scope.offset == 50


def test_scope_intersects_feature_contracts_without_widening() -> None:
    filters = NormalizedFilters(
        customer_ids=["C1", "C2"],
        country="US",
        transaction_type="cash_deposit",
        currency="USD",
        amount_min=Decimal("10.25"),
        amount_max=Decimal("30.00"),
    )
    scope = QueryScope.from_filters(
        filters,
        entity_scope=EntityScope(
            entity_type=EntityType.CUSTOMER,
            entity_ids=("C2", "C3"),
        ),
        transaction_filter=TransactionFilter(
            countries=("US", "GB"),
            transaction_types=("cash_deposit", "wire"),
            currency="USD",
            minimum_amount_minor=2_000,
            maximum_amount_minor=2_500,
        ),
    )

    assert scope.customer_ids == ("C2",)
    assert scope.countries == ("US",)
    assert scope.transaction_types == ("cash_deposit",)
    assert scope.minimum_amount_minor == 2_000
    assert scope.maximum_amount_minor == 2_500
    assert not scope.is_empty


@pytest.mark.parametrize(
    ("filters", "feature_scope"),
    [
        (
            NormalizedFilters(customer_ids=["C1"]),
            EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C2",)),
        ),
        (
            NormalizedFilters(country="US"),
            TransactionFilter(countries=("GB",)),
        ),
        (
            NormalizedFilters(currency="USD"),
            TransactionFilter(currency="EUR"),
        ),
        (
            NormalizedFilters(
                currency="USD",
                amount_min=Decimal("20"),
            ),
            TransactionFilter(maximum_amount_minor=1_000),
        ),
    ],
)
def test_disjoint_intersections_are_explicitly_empty(
    filters: NormalizedFilters,
    feature_scope: EntityScope | TransactionFilter,
) -> None:
    if isinstance(feature_scope, EntityScope):
        scope = QueryScope.from_filters(filters, entity_scope=feature_scope)
    else:
        scope = QueryScope.from_filters(filters, transaction_filter=feature_scope)
    assert scope.is_empty
    assert scope.empty_reason


def test_equal_time_bounds_create_empty_scope() -> None:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    scope = QueryScope.from_filters(NormalizedFilters(date_from=instant, date_to=instant))
    assert scope.is_empty
    assert scope.start_inclusive == scope.end_exclusive


def test_feature_request_window_is_intersected_with_normalized_dates() -> None:
    request = FeatureRequest(
        operation="transaction_count",
        version="v1",
        as_of=datetime(2026, 1, 4, tzinfo=UTC),
        window=FeatureWindow(
            start_inclusive=datetime(2026, 1, 1, tzinfo=UTC),
            end_exclusive=datetime(2026, 1, 4, tzinfo=UTC),
        ),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C1",)),
    )
    scope = QueryScope.from_feature_request(
        NormalizedFilters(
            date_from=datetime(2026, 1, 2, tzinfo=UTC),
            date_to=datetime(2026, 1, 3, tzinfo=UTC),
        ),
        request,
    )
    assert scope.start_inclusive == datetime(2026, 1, 2, tzinfo=UTC)
    assert scope.end_exclusive == datetime(2026, 1, 3, tzinfo=UTC)
    assert scope.customer_ids == ("C1",)


def test_pattern_filter_must_be_resolved_before_transaction_query() -> None:
    with pytest.raises(ValueError, match="pattern_type"):
        QueryScope.from_filters(NormalizedFilters(pattern_type=PatternType.VELOCITY))


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        (Decimal("12.34"), "USD", 1_234),
        (Decimal("12"), "JPY", 12),
        (Decimal("12.345"), "KWD", 12_345),
    ],
)
def test_amount_conversion_uses_currency_minor_unit(
    amount: Decimal,
    currency: str,
    expected: int,
) -> None:
    assert amount_to_minor(amount, currency) == expected


def test_amount_conversion_rejects_ambiguity_and_excess_precision() -> None:
    with pytest.raises(ValueError, match="explicit currency"):
        QueryScope.from_filters(NormalizedFilters(amount_min=Decimal("1")))
    with pytest.raises(ValueError, match="precision"):
        amount_to_minor(Decimal("1.001"), "USD")


def test_pagination_validation_is_deterministic() -> None:
    filters = NormalizedFilters(max_results=10)
    with pytest.raises(ValueError, match="both"):
        QueryScope.from_filters(filters, page=2, offset=1)
    with pytest.raises(ValueError, match="at least"):
        QueryScope.from_filters(filters, page=0)
    with pytest.raises(ValueError, match="negative"):
        QueryScope.from_filters(filters, offset=-1)
