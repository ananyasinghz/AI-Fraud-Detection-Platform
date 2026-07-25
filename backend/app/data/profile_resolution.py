"""Effective-dated customer profile resolution."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from backend.app.data.models import CustomerProfile
from backend.app.domain.base import is_timezone_aware


@dataclass(frozen=True)
class ProfileResolution:
    """Profile active at one instant plus explicit data-quality warnings."""

    profile: CustomerProfile | None
    warnings: tuple[str, ...]


def active_profile_statement(customer_id: str, as_of: datetime) -> Select[tuple[CustomerProfile]]:
    """Build the canonical half-open interval lookup."""
    if not is_timezone_aware(as_of):
        raise ValueError("profile resolution requires a timezone-aware as_of")
    return (
        select(CustomerProfile)
        .where(
            CustomerProfile.customer_id == customer_id,
            CustomerProfile.profile_effective_from <= as_of,
            or_(
                CustomerProfile.profile_effective_to.is_(None),
                CustomerProfile.profile_effective_to > as_of,
            ),
        )
        .order_by(CustomerProfile.profile_effective_from.desc())
        .limit(1)
    )


def resolve_profile_as_of(
    session: Session,
    customer_id: str,
    as_of: datetime,
) -> ProfileResolution:
    """Resolve a profile without substituting zeroes for missing declarations."""
    profile = session.scalar(active_profile_statement(customer_id, as_of))
    if profile is None:
        return ProfileResolution(
            profile=None,
            warnings=("No customer profile was effective at the requested time.",),
        )

    warnings: list[str] = []
    if profile.declared_annual_income_minor is None and profile.declared_revenue_band is None:
        warnings.append("Declared income or revenue is unavailable.")
    if (
        profile.expected_monthly_volume_min_minor is None
        or profile.expected_monthly_volume_max_minor is None
    ):
        warnings.append("Expected monthly activity range is incomplete.")
    if profile.volume_currency is None:
        warnings.append("Expected activity currency is unavailable.")
    return ProfileResolution(profile=profile, warnings=tuple(warnings))
