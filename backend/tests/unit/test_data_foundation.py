"""Database schema, invariant, and repository tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from alembic import command
from backend.app.core.config import get_settings
from backend.app.data.database import (
    create_database_engine,
    session_factory,
    session_scope,
)
from backend.app.data.models import Customer, CustomerProfile
from backend.app.data.repositories import CustomerRepository, TransactionRepository


def _migrate_database(path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setenv("FRAUD_DATABASE_URL", url)
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    get_settings.cache_clear()
    return url


def test_migration_creates_tables_foreign_keys_and_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "schema.db"
    url = _migrate_database(database_path, monkeypatch)
    engine = create_database_engine(url)
    inspector = inspect(engine)
    assert {
        "dataset_runs",
        "customers",
        "customer_profiles",
        "accounts",
        "counterparties",
        "devices",
        "transactions",
        "investigations",
        "alerts",
        "alert_events",
    }.issubset(inspector.get_table_names())
    assert inspector.get_foreign_keys("transactions")
    transaction_indexes = {index["name"] for index in inspector.get_indexes("transactions")}
    assert {
        "ix_txn_customer_occurred",
        "ix_txn_account_occurred",
        "ix_txn_amount",
        "ix_txn_type",
        "ix_txn_country",
        "ix_txn_ml_eligible",
    }.issubset(transaction_indexes)
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO accounts "
                    "(account_id, customer_id, account_type, currency, opened_at, status) "
                    "VALUES ('missing-fk', 'missing', 'checking', 'USD', "
                    "'2026-01-01T00:00:00+00:00', 'active')"
                )
            )
    engine.dispose()


def test_profile_resolution_overlap_and_missing_fields(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'profiles.db').as_posix()}")
    from backend.app.data.models import Base

    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    start = datetime(2025, 1, 1, tzinfo=UTC)
    change = datetime(2026, 1, 1, tzinfo=UTC)
    with session_scope(factory) as session:
        repository = CustomerRepository(session)
        repository.add_customer(Customer(customer_id="c-1", created_at=start, status="active"))
        session.flush()
        repository.add_profile(
            CustomerProfile(
                customer_id="c-1",
                segment="retail",
                residence_country="US",
                profile_effective_from=start,
                profile_effective_to=change,
                profile_source="test",
                pep_flag=False,
            )
        )
        session.flush()
        repository.add_profile(
            CustomerProfile(
                customer_id="c-1",
                segment="retail",
                residence_country="US",
                declared_annual_income_minor=5_000_000,
                income_currency="USD",
                expected_monthly_volume_min_minor=10_000,
                expected_monthly_volume_max_minor=100_000,
                volume_currency="USD",
                profile_effective_from=change,
                profile_source="test",
                pep_flag=False,
            )
        )
        session.flush()
        old = repository.get_profile_as_of("c-1", start + timedelta(days=1))
        assert old.profile is not None
        assert old.profile.profile_effective_to == change
        assert len(old.warnings) == 3
        current = repository.get_profile_as_of("c-1", change)
        assert current.profile is not None
        assert current.profile.declared_annual_income_minor == 5_000_000
        assert current.warnings == ()
        missing = repository.get_profile_as_of("unknown", change)
        assert missing.profile is None
        assert missing.warnings
        with pytest.raises(ValueError, match="overlaps"):
            repository.add_profile(
                CustomerProfile(
                    customer_id="c-1",
                    segment="retail",
                    residence_country="US",
                    profile_effective_from=change - timedelta(days=1),
                    profile_source="test",
                    pep_flag=False,
                )
            )
        with pytest.raises(ValueError, match="timezone-aware"):
            repository.get_profile_as_of("c-1", datetime(2026, 1, 1))
    engine.dispose()


def test_utc_type_and_transaction_query_guards(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{(tmp_path / 'guards.db').as_posix()}")
    from backend.app.data.models import Base

    Base.metadata.create_all(engine)
    factory = session_factory(engine)
    with pytest.raises(StatementError, match="timezone"), session_scope(factory) as session:
        session.add(Customer(customer_id="naive", created_at=datetime(2026, 1, 1)))
        session.flush()

    with session_scope(factory) as session:
        repository = TransactionRepository(session)
        aware = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="timezone"):
            repository.list_for_customer(
                "c-1",
                date_from=datetime(2026, 1, 1),
                date_to=aware,
            )
        with pytest.raises(ValueError, match="after"):
            repository.list_for_customer(
                "c-1",
                date_from=aware + timedelta(days=1),
                date_to=aware,
            )
        with pytest.raises(ValueError, match="limit"):
            repository.list_for_customer(
                "c-1",
                date_from=aware,
                date_to=aware,
                limit=0,
            )
    engine.dispose()
