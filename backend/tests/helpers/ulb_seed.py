"""Seed helpers for Phase 3 ML-eligible ulb_attached transactions."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.app.data.models import (
    Account,
    Customer,
    DatasetRun,
    Transaction,
)


def ensure_run(session: Session, run_id: str = "ulb-phase3-fixture") -> None:
    existing = session.get(DatasetRun, run_id)
    if existing is not None:
        return
    session.add(
        DatasetRun(
            run_id=run_id,
            run_kind="aml_seed",
            alembic_revision="head",
            record_counts={"transactions": 1},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    session.flush()


def seed_ulb_attached_transaction(
    session: Session,
    *,
    transaction_id: str = "TX-ULB-0",
    customer_id: str = "C-ULB",
    account_id: str = "A-ULB",
    fixture_row: int = 0,
    run_id: str = "ulb-phase3-fixture",
    occurred_at: datetime | None = None,
) -> Transaction:
    """Insert one ml_eligible ulb_attached row pointing at creditcard_tiny.csv."""
    ensure_run(session, run_id)
    if session.get(Customer, customer_id) is None:
        session.add(
            Customer(
                customer_id=customer_id,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                status="active",
            )
        )
        session.flush()
    if session.get(Account, account_id) is None:
        session.add(
            Account(
                account_id=account_id,
                customer_id=customer_id,
                account_type="checking",
                currency="USD",
                country="US",
                opened_at=datetime(2026, 1, 1, tzinfo=UTC),
                status="active",
            )
        )
        session.flush()
    transaction = Transaction(
        transaction_id=transaction_id,
        customer_id=customer_id,
        account_id=account_id,
        occurred_at=occurred_at or datetime(2026, 1, 15, tzinfo=UTC),
        amount_minor=12345,
        currency="USD",
        direction="debit",
        transaction_type="card_purchase",
        channel="card",
        country="US",
        ml_eligible=True,
        ml_feature_ref=f"fixture:creditcard_tiny.csv:{fixture_row}",
        data_source="ulb_attached",
        seed_run_id=run_id,
    )
    session.add(transaction)
    session.flush()
    return transaction
