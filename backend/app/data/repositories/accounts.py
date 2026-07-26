"""Account lookups and deterministic tenure calculations."""

from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from backend.app.data.models import Account
from backend.app.domain.base import is_timezone_aware


class AccountRepository:
    """Read accounts without losing explicit customer or identifier scopes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, account_id: str) -> Account | None:
        """Return one account by its stable identifier."""
        return self._session.get(Account, account_id)

    def get(self, account_id: str) -> Account | None:
        """Compatibility alias for a single-account lookup."""
        return self.get_by_id(account_id)

    def get_many(self, account_ids: tuple[str, ...]) -> list[Account]:
        """Return only requested accounts in deterministic identifier order."""
        if not account_ids:
            return []
        statement: Select[tuple[Account]] = (
            select(Account).where(Account.account_id.in_(account_ids)).order_by(Account.account_id)
        )
        return list(self._session.scalars(statement))

    def list_for_customer(
        self,
        customer_id: str,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[Account]:
        """Return a bounded, stable page of a customer's accounts."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        statement: Select[tuple[Account]] = (
            select(Account)
            .where(Account.customer_id == customer_id)
            .order_by(Account.opened_at, Account.account_id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def tenure_days(self, account_id: str, *, as_of: datetime) -> int | None:
        """Return complete UTC days since opening, or None for an unknown account."""
        if not is_timezone_aware(as_of):
            raise ValueError("account tenure requires a timezone-aware as_of")
        account = self.get_by_id(account_id)
        if account is None:
            return None
        normalized_as_of = as_of.astimezone(UTC)
        opened_at = account.opened_at.astimezone(UTC)
        if normalized_as_of < opened_at:
            raise ValueError("as_of cannot be before the account opening time")
        return (normalized_as_of - opened_at).days

    def account_tenure_days(self, account_id: str, *, as_of: datetime) -> int | None:
        """Named feature-style alias for tenure_days."""
        return self.tenure_days(account_id, as_of=as_of)
