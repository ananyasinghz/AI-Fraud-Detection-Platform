"""Integration tests for scope-preserving repositories."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, event

from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import (
    Account,
    Base,
    Customer,
    CustomerProfile,
    DatasetRun,
    Transaction,
)
from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import AccountRepository, TransactionRepository
from backend.app.domain.enums import EntityType, TransactionDirection
from backend.app.domain.features import EntityScope, TransactionFilter
from backend.app.domain.filters import NormalizedFilters

START = datetime(2026, 1, 1, tzinfo=UTC)


def _transaction(
    transaction_id: str,
    *,
    customer_id: str = "C1",
    account_id: str = "A1",
    occurred_at: datetime,
    amount_minor: int = 2_000,
    currency: str = "USD",
    transaction_type: str = "cash_deposit",
    country: str = "US",
    direction: str = "credit",
    channel: str = "branch",
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
        channel=channel,
        country=country,
        ml_eligible=False,
        data_source="synthetic",
        seed_run_id="run-1",
    )


def _seed(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        session.add(
            DatasetRun(
                run_id="run-1",
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
                    opened_at=START - timedelta(days=10, hours=12),
                    status="active",
                ),
                Account(
                    account_id="A2",
                    customer_id="C2",
                    account_type="checking",
                    currency="USD",
                    country="GB",
                    opened_at=START - timedelta(days=2),
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
                    profile_effective_from=START - timedelta(days=10),
                    profile_effective_to=START + timedelta(days=1),
                    profile_source="test",
                    pep_flag=False,
                ),
                CustomerProfile(
                    customer_id="C1",
                    segment="corporate",
                    residence_country="US",
                    profile_effective_from=START + timedelta(days=1),
                    profile_source="test",
                    pep_flag=False,
                ),
                CustomerProfile(
                    customer_id="C2",
                    segment="retail",
                    residence_country="GB",
                    profile_effective_from=START - timedelta(days=10),
                    profile_source="test",
                    pep_flag=False,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                _transaction("T-start", occurred_at=START),
                _transaction("T-match", occurred_at=START + timedelta(hours=1)),
                _transaction(
                    "T-wrong-type",
                    occurred_at=START + timedelta(hours=2),
                    transaction_type="wire",
                ),
                _transaction(
                    "T-other",
                    customer_id="C2",
                    account_id="A2",
                    occurred_at=START + timedelta(hours=3),
                    country="GB",
                ),
                _transaction("T-end", occurred_at=START + timedelta(days=1)),
            ]
        )


def test_list_scoped_applies_all_filters_and_half_open_bounds(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'scoped.db').as_posix()}")
    _seed(engine)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        scope = QueryScope.from_filters(
            NormalizedFilters(
                date_from=START,
                date_to=START + timedelta(days=1),
                customer_ids=["C1"],
                account_ids=["A1"],
                transaction_ids=["T-match", "T-wrong-type", "T-end"],
                segment="retail",
                country="US",
                transaction_type="cash_deposit",
                currency="USD",
                amount_min=Decimal("20.00"),
                amount_max=Decimal("20.00"),
            ),
            as_of=START,
            entity_scope=EntityScope(
                entity_type=EntityType.TRANSACTION,
                entity_ids=("T-match", "T-end"),
            ),
            transaction_filter=TransactionFilter(
                directions=(TransactionDirection.CREDIT,),
                channels=("branch",),
            ),
        )
        result = TransactionRepository(session).list_scoped(scope)
        assert [item.transaction_id for item in result] == ["T-match"]
    engine.dispose()


def test_list_scoped_uses_profile_effective_at_as_of(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'profiles.db').as_posix()}")
    _seed(engine)
    factory = session_factory(engine)
    filters = NormalizedFilters(
        date_from=START,
        date_to=START + timedelta(days=1),
        customer_ids=["C1"],
        segment="retail",
    )
    with session_scope(factory) as session:
        repository = TransactionRepository(session)
        old_scope = QueryScope.from_filters(filters, as_of=START)
        assert repository.list_scoped(old_scope)
        changed_scope = QueryScope.from_filters(filters, as_of=START + timedelta(days=1))
        assert repository.list_scoped(changed_scope) == []
    engine.dispose()


def test_list_scoped_has_stable_pagination_and_utc_offsets(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'pages.db').as_posix()}")
    _seed(engine)
    factory = session_factory(engine)
    local_zone = timezone(timedelta(hours=-5))
    filters = NormalizedFilters(
        date_from=(START - timedelta(hours=5)).astimezone(local_zone),
        date_to=(START + timedelta(days=1)).astimezone(local_zone),
        customer_ids=["C1"],
        max_results=2,
    )
    with session_scope(factory) as session:
        repository = TransactionRepository(session)
        first = repository.list_scoped(QueryScope.from_filters(filters, page=1))
        second = repository.list_scoped(QueryScope.from_filters(filters, page=2))
        assert [item.transaction_id for item in first] == ["T-start", "T-match"]
        assert [item.transaction_id for item in second] == ["T-wrong-type"]
    engine.dispose()


def test_empty_scope_short_circuits_without_sql(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    _seed(engine)
    factory = session_factory(engine)
    statements: list[str] = []

    def record_statement(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    with session_scope(factory) as session:
        scope = QueryScope.from_filters(
            NormalizedFilters(customer_ids=["C1"]),
            entity_scope=EntityScope(
                entity_type=EntityType.CUSTOMER,
                entity_ids=("C2",),
            ),
        )
        assert TransactionRepository(session).list_scoped(scope) == []
        assert statements == []
    event.remove(engine, "before_cursor_execute", record_statement)
    engine.dispose()


def test_account_repository_lookups_pagination_and_tenure(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'accounts.db').as_posix()}")
    _seed(engine)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        repository = AccountRepository(session)
        assert repository.get_by_id("A1") is not None
        assert repository.get_by_id("missing") is None
        assert [item.account_id for item in repository.get_many(("A2", "A1"))] == ["A1", "A2"]
        assert [item.account_id for item in repository.list_for_customer("C1")] == ["A1"]
        assert repository.account_tenure_days("A1", as_of=START) == 10
        assert repository.tenure_days("missing", as_of=START) is None
    engine.dispose()
