"""Customer and profile persistence."""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.data.models import Customer, CustomerProfile
from backend.app.data.profile_resolution import ProfileResolution, resolve_profile_as_of


class CustomerRepository:
    """Small repository with effective-date invariants."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_customer(self, customer: Customer) -> None:
        self._session.add(customer)

    def add_profile(self, profile: CustomerProfile) -> None:
        conditions = [
            CustomerProfile.customer_id == profile.customer_id,
            or_(
                CustomerProfile.profile_effective_to.is_(None),
                CustomerProfile.profile_effective_to > profile.profile_effective_from,
            ),
        ]
        if profile.profile_effective_to is not None:
            conditions.append(
                CustomerProfile.profile_effective_from < profile.profile_effective_to,
            )
        overlap = self._session.scalar(select(CustomerProfile.profile_id).where(*conditions))
        if overlap is not None:
            raise ValueError(
                f"profile interval overlaps an existing profile for {profile.customer_id}"
            )
        self._session.add(profile)

    def get_profile_as_of(
        self,
        customer_id: str,
        as_of: datetime,
    ) -> ProfileResolution:
        return resolve_profile_as_of(self._session, customer_id, as_of)
