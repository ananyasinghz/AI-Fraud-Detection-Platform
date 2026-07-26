"""Scoped transaction persistence queries."""

from datetime import datetime

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import Session

from backend.app.data.models import CustomerProfile, Transaction
from backend.app.data.query_scope import QueryScope
from backend.app.domain.base import is_timezone_aware


class TransactionRepository:
    """Read transactions through explicit entity and time scopes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, transaction_id: str) -> Transaction | None:
        return self._session.get(Transaction, transaction_id)

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

    def list_scoped(self, scope: QueryScope) -> list[Transaction]:
        """List transactions while preserving every resolved scope predicate."""
        if scope.is_empty:
            return []

        conditions = [
            Transaction.occurred_at >= scope.start_inclusive,
            Transaction.occurred_at < scope.end_exclusive,
        ]
        if scope.customer_ids:
            conditions.append(Transaction.customer_id.in_(scope.customer_ids))
        if scope.account_ids:
            conditions.append(Transaction.account_id.in_(scope.account_ids))
        if scope.transaction_ids:
            conditions.append(Transaction.transaction_id.in_(scope.transaction_ids))
        if scope.countries:
            conditions.append(Transaction.country.in_(scope.countries))
        if scope.transaction_types:
            conditions.append(Transaction.transaction_type.in_(scope.transaction_types))
        if scope.directions:
            conditions.append(Transaction.direction.in_(scope.directions))
        if scope.channels:
            conditions.append(Transaction.channel.in_(scope.channels))
        if scope.currency is not None:
            conditions.append(Transaction.currency == scope.currency)
        if scope.minimum_amount_minor is not None:
            conditions.append(Transaction.amount_minor >= scope.minimum_amount_minor)
        if scope.maximum_amount_minor is not None:
            conditions.append(Transaction.amount_minor <= scope.maximum_amount_minor)
        if scope.segment is not None:
            conditions.append(
                exists(
                    select(CustomerProfile.profile_id).where(
                        CustomerProfile.customer_id == Transaction.customer_id,
                        CustomerProfile.segment == scope.segment,
                        CustomerProfile.profile_effective_from <= scope.as_of,
                        or_(
                            CustomerProfile.profile_effective_to.is_(None),
                            CustomerProfile.profile_effective_to > scope.as_of,
                        ),
                    )
                )
            )

        statement: Select[tuple[Transaction]] = (
            select(Transaction)
            .where(*conditions)
            .order_by(Transaction.occurred_at, Transaction.transaction_id)
            .limit(scope.limit)
            .offset(scope.offset)
        )
        return list(self._session.scalars(statement))
