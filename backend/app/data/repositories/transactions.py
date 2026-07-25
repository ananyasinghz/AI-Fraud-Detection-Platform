"""Scoped transaction persistence queries."""

from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from backend.app.data.models import Transaction
from backend.app.domain.base import is_timezone_aware


class TransactionRepository:
    """Read transactions through explicit entity and time scopes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_customer(
        self,
        customer_id: str,
        *,
        date_from: datetime,
        date_to: datetime,
        limit: int = 1000,
    ) -> list[Transaction]:
        if not is_timezone_aware(date_from) or not is_timezone_aware(date_to):
            raise ValueError("transaction query boundaries must include a timezone")
        if date_from > date_to:
            raise ValueError("date_from cannot be after date_to")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        statement: Select[tuple[Transaction]] = (
            select(Transaction)
            .where(
                Transaction.customer_id == customer_id,
                Transaction.occurred_at >= date_from,
                Transaction.occurred_at <= date_to,
            )
            .order_by(Transaction.occurred_at, Transaction.transaction_id)
            .limit(limit)
        )
        return list(self._session.scalars(statement))
