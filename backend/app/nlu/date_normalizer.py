"""Resolve relative date tokens from request as_of (no LLM calendar math)."""

from __future__ import annotations

from calendar import monthrange
from datetime import UTC, datetime, timedelta
from typing import Literal

RelativeDateToken = Literal[
    "last_30_days",
    "this_month",
    "last_7_days",
    "last_90_days",
    "none",
]


def normalize_relative_window(
    token: str | None,
    *,
    as_of: datetime,
) -> tuple[datetime | None, datetime | None]:
    """Return UTC half-open [date_from, date_to) bounds from a relative token."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    as_of_utc = as_of.astimezone(UTC)
    if token is None or token in {"", "none", "null"}:
        return None, None
    normalized = token.strip().lower()
    end = as_of_utc
    if normalized == "last_30_days":
        return as_of_utc - timedelta(days=30), end
    if normalized == "last_7_days":
        return as_of_utc - timedelta(days=7), end
    if normalized == "last_90_days":
        return as_of_utc - timedelta(days=90), end
    if normalized == "this_month":
        start = datetime(as_of_utc.year, as_of_utc.month, 1, tzinfo=UTC)
        return start, end
    if normalized == "this_month_full":
        start = datetime(as_of_utc.year, as_of_utc.month, 1, tzinfo=UTC)
        last_day = monthrange(as_of_utc.year, as_of_utc.month)[1]
        end_exclusive = datetime(
            as_of_utc.year,
            as_of_utc.month,
            last_day,
            tzinfo=UTC,
        ) + timedelta(days=1)
        return start, end_exclusive
    raise ValueError(f"unsupported relative date token: {token}")


def apply_relative_dates(
    *,
    as_of: datetime,
    relative_date: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime | None, datetime | None, list[str]]:
    """Prefer explicit absolute dates; otherwise resolve relative_date from as_of."""
    ambiguities: list[str] = []
    if date_from is not None or date_to is not None:
        if relative_date and relative_date not in {"none", "null", ""}:
            ambiguities.append("relative_date_ignored_absolute_present")
        return date_from, date_to, ambiguities
    if not relative_date:
        return None, None, ambiguities
    try:
        resolved_from, resolved_to = normalize_relative_window(relative_date, as_of=as_of)
    except ValueError:
        ambiguities.append(f"unresolved_relative_date:{relative_date}")
        return None, None, ambiguities
    return resolved_from, resolved_to, ambiguities
