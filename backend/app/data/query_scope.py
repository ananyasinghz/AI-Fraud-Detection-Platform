"""Resolve public query filters into an explicit, non-widening database scope."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from backend.app.domain.enums import EntityType, TransactionDirection
from backend.app.domain.features import EntityScope, FeatureRequest, TransactionFilter
from backend.app.domain.filters import NormalizedFilters

MIN_UTC = datetime.min.replace(tzinfo=UTC)
MAX_UTC = datetime.max.replace(tzinfo=UTC)
MAX_QUERY_LIMIT = 1000

_ZERO_DECIMAL_CURRENCIES = frozenset(
    {
        "BIF",
        "CLP",
        "DJF",
        "GNF",
        "ISK",
        "JPY",
        "KMF",
        "KRW",
        "PYG",
        "RWF",
        "UGX",
        "UYI",
        "VND",
        "VUV",
        "XAF",
        "XOF",
        "XPF",
    }
)
_THREE_DECIMAL_CURRENCIES = frozenset({"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"})


def _utc(value: datetime) -> datetime:
    """Return an aware datetime normalized to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("query boundaries must include a timezone")
    return value.astimezone(UTC)


def _minor_unit_exponent(currency: str) -> int:
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return 0
    if currency in _THREE_DECIMAL_CURRENCIES:
        return 3
    return 2


def amount_to_minor(amount: Decimal, currency: str | None) -> int:
    """Convert a major-unit amount exactly, rejecting currency/precision ambiguity."""
    if currency is None:
        raise ValueError("amount filters require an explicit currency")
    scaled = amount * (Decimal(10) ** _minor_unit_exponent(currency))
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ValueError(f"amount has more precision than {currency} minor units")
    return int(integral)


def _intersection(
    left: tuple[str, ...],
    right: tuple[str, ...],
) -> tuple[tuple[str, ...], bool]:
    """Intersect restrictions; an empty input means unrestricted."""
    if not left:
        return right, False
    if not right:
        return left, False
    right_values = set(right)
    result = tuple(value for value in left if value in right_values)
    return result, not result


@dataclass(frozen=True, slots=True)
class QueryScope:
    """Fully resolved transaction query boundaries and predicates."""

    start_inclusive: datetime
    end_exclusive: datetime
    as_of: datetime
    customer_ids: tuple[str, ...] = ()
    account_ids: tuple[str, ...] = ()
    transaction_ids: tuple[str, ...] = ()
    segment: str | None = None
    countries: tuple[str, ...] = ()
    transaction_types: tuple[str, ...] = ()
    directions: tuple[TransactionDirection, ...] = ()
    channels: tuple[str, ...] = ()
    currency: str | None = None
    minimum_amount_minor: int | None = None
    maximum_amount_minor: int | None = None
    limit: int = 100
    offset: int = 0
    is_empty: bool = False
    empty_reason: str | None = None

    @property
    def country(self) -> str | None:
        """Return the single country used by NormalizedFilters, when singular."""
        return self.countries[0] if len(self.countries) == 1 else None

    @property
    def transaction_type(self) -> str | None:
        """Return the single transaction type, when singular."""
        return self.transaction_types[0] if len(self.transaction_types) == 1 else None

    @classmethod
    def from_filters(
        cls,
        filters: NormalizedFilters,
        *,
        as_of: datetime | None = None,
        entity_scope: EntityScope | None = None,
        transaction_filter: TransactionFilter | None = None,
        limit: int | None = None,
        offset: int = 0,
        page: int | None = None,
    ) -> "QueryScope":
        """Resolve filters and optional feature contracts without widening either."""
        if filters.pattern_type is not None:
            raise ValueError(
                "pattern_type cannot be represented by a transaction query; "
                "resolve it to explicit transaction predicates first"
            )
        if limit is not None and not 1 <= limit <= MAX_QUERY_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_QUERY_LIMIT}")
        resolved_limit = min(filters.max_results, limit or filters.max_results)
        if offset < 0:
            raise ValueError("offset cannot be negative")
        if page is not None:
            if page < 1:
                raise ValueError("page must be at least 1")
            if offset:
                raise ValueError("page and offset cannot both be specified")
            offset = (page - 1) * resolved_limit

        start = _utc(filters.date_from) if filters.date_from is not None else MIN_UTC
        end = _utc(filters.date_to) if filters.date_to is not None else MAX_UTC
        resolved_as_of = _utc(as_of) if as_of is not None else end

        customers = tuple(filters.customer_ids)
        accounts = tuple(filters.account_ids)
        transactions = tuple(filters.transaction_ids)
        empty_reasons: list[str] = []
        if entity_scope is not None:
            entity_ids = tuple(entity_scope.entity_ids)
            if entity_scope.entity_type is EntityType.CUSTOMER:
                customers, empty = _intersection(customers, entity_ids)
            elif entity_scope.entity_type is EntityType.ACCOUNT:
                accounts, empty = _intersection(accounts, entity_ids)
            else:
                transactions, empty = _intersection(transactions, entity_ids)
            if empty:
                empty_reasons.append("entity scope does not intersect normalized filters")

        countries: tuple[str, ...] = (filters.country,) if filters.country is not None else ()
        transaction_types: tuple[str, ...] = (
            (filters.transaction_type,) if filters.transaction_type is not None else ()
        )
        directions: tuple[TransactionDirection, ...] = ()
        channels: tuple[str, ...] = ()
        currency = filters.currency
        minimum = filters.amount_min
        maximum = filters.amount_max

        if transaction_filter is not None:
            countries, empty = _intersection(countries, transaction_filter.countries)
            if empty:
                empty_reasons.append("country filters do not intersect")
            transaction_types, empty = _intersection(
                transaction_types, transaction_filter.transaction_types
            )
            if empty:
                empty_reasons.append("transaction type filters do not intersect")
            directions = transaction_filter.directions
            channels = transaction_filter.channels
            if currency is not None and transaction_filter.currency is not None:
                if currency != transaction_filter.currency:
                    empty_reasons.append("currency filters do not intersect")
            elif transaction_filter.currency is not None:
                currency = transaction_filter.currency

        minimum_minor = amount_to_minor(minimum, currency) if minimum is not None else None
        maximum_minor = amount_to_minor(maximum, currency) if maximum is not None else None
        if transaction_filter is not None:
            requested_minimum = transaction_filter.minimum_amount_minor
            requested_maximum = transaction_filter.maximum_amount_minor
            if requested_minimum is not None:
                minimum_minor = max(minimum_minor or 0, requested_minimum)
            if requested_maximum is not None:
                maximum_minor = (
                    requested_maximum
                    if maximum_minor is None
                    else min(maximum_minor, requested_maximum)
                )

        if start >= end:
            empty_reasons.append("time window is empty")
        if (
            minimum_minor is not None
            and maximum_minor is not None
            and minimum_minor > maximum_minor
        ):
            empty_reasons.append("amount filters do not intersect")

        reason = "; ".join(empty_reasons) or None
        return cls(
            start_inclusive=start,
            end_exclusive=end,
            as_of=resolved_as_of,
            customer_ids=customers,
            account_ids=accounts,
            transaction_ids=transactions,
            segment=filters.segment,
            countries=countries,
            transaction_types=transaction_types,
            directions=directions,
            channels=channels,
            currency=currency,
            minimum_amount_minor=minimum_minor,
            maximum_amount_minor=maximum_minor,
            limit=resolved_limit,
            offset=offset,
            is_empty=bool(empty_reasons),
            empty_reason=reason,
        )

    @classmethod
    def from_feature_request(
        cls,
        filters: NormalizedFilters,
        request: FeatureRequest,
        *,
        limit: int | None = None,
        offset: int = 0,
        page: int | None = None,
    ) -> "QueryScope":
        """Intersect normalized filters with every scope in a feature request."""
        scope = cls.from_filters(
            filters,
            as_of=request.as_of,
            entity_scope=request.scope,
            transaction_filter=request.transaction_filter,
            limit=limit,
            offset=offset,
            page=page,
        )
        start = max(scope.start_inclusive, request.window.start_inclusive)
        end = min(scope.end_exclusive, request.window.end_exclusive)
        if start >= end:
            reason = "feature window does not intersect normalized date filters"
            if scope.empty_reason is not None:
                reason = f"{scope.empty_reason}; {reason}"
            return replace(
                scope,
                start_inclusive=start,
                end_exclusive=end,
                is_empty=True,
                empty_reason=reason,
            )
        return replace(scope, start_inclusive=start, end_exclusive=end)

    @classmethod
    def empty(cls, *, reason: str, as_of: datetime, limit: int = 100) -> "QueryScope":
        """Create an explicit no-data scope."""
        instant = _utc(as_of)
        return cls(
            start_inclusive=instant,
            end_exclusive=instant,
            as_of=instant,
            limit=limit,
            is_empty=True,
            empty_reason=reason,
        )

    def with_empty(self, reason: str) -> "QueryScope":
        """Preserve this scope while marking it as known empty."""
        return replace(self, is_empty=True, empty_reason=reason)


def resolve_query_scope(
    filters: NormalizedFilters,
    *,
    as_of: datetime | None = None,
    entity_scope: EntityScope | None = None,
    transaction_filter: TransactionFilter | None = None,
    limit: int | None = None,
    offset: int = 0,
    page: int | None = None,
) -> QueryScope:
    """Convenience entry point for resolving normalized filters."""
    return QueryScope.from_filters(
        filters,
        as_of=as_of,
        entity_scope=entity_scope,
        transaction_filter=transaction_filter,
        limit=limit,
        offset=offset,
        page=page,
    )


__all__ = ["MAX_QUERY_LIMIT", "QueryScope", "amount_to_minor", "resolve_query_scope"]
