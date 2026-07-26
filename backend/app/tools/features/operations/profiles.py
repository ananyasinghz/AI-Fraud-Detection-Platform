"""Effective-profile, account-tenure, and data-quality feature operations."""

from decimal import Decimal

from backend.app.data.profile_resolution import ProfileResolution, resolve_profile_as_of
from backend.app.data.repositories import AccountRepository
from backend.app.domain.features import FeatureWarning
from backend.app.tools.features.operations.common import (
    OperationContext,
    OperationOutput,
    boolean,
    decimal,
    denominator,
    integer,
    money_unit,
    scoped_money_total,
    warning,
)

SECONDS_PER_DAY = Decimal(86400)
MONTH_DAYS = Decimal(30)
YEAR_DAYS = Decimal(365)


def _profiles(context: OperationContext) -> tuple[ProfileResolution, ...]:
    return tuple(
        resolve_profile_as_of(context.session, customer_id, context.request.as_of)
        for customer_id in context.customer_ids()
    )


def _profile_warnings(resolutions: tuple[ProfileResolution, ...]) -> tuple[FeatureWarning, ...]:
    messages = sorted({message for item in resolutions for message in item.warnings})
    warnings = [warning("PROFILE_DATA_MISSING", message) for message in messages]
    missing_count = sum(item.profile is None for item in resolutions)
    if missing_count:
        warnings.append(
            warning(
                "PROFILE_NOT_FOUND",
                f"No effective profile was found for {missing_count} scoped customers.",
            )
        )
    return tuple(warnings)


def _window_days(context: OperationContext) -> Decimal:
    duration = context.scope.end_exclusive - context.scope.start_inclusive
    seconds = Decimal(duration.days * 86400 + duration.seconds) + (
        Decimal(duration.microseconds) / Decimal(1_000_000)
    )
    return seconds / SECONDS_PER_DAY


def activity_vs_expected(context: OperationContext) -> OperationOutput:
    resolutions = _profiles(context)
    profiles = tuple(item.profile for item in resolutions if item.profile is not None)
    observed = scoped_money_total(context)
    expected_min_total = Decimal(0)
    expected_max_total = Decimal(0)
    usable = bool(profiles) and len(profiles) == len(resolutions) and context.currency is not None
    for profile in profiles:
        if (
            profile.expected_monthly_volume_min_minor is None
            or profile.expected_monthly_volume_max_minor is None
            or profile.volume_currency != context.currency
        ):
            usable = False
            break
        expected_min_total += Decimal(profile.expected_monthly_volume_min_minor)
        expected_max_total += Decimal(profile.expected_monthly_volume_max_minor)
    if usable:
        scale = _window_days(context) / MONTH_DAYS
        expected_min: Decimal | None = expected_min_total * scale
        expected_max: Decimal | None = expected_max_total * scale
    else:
        expected_min = None
        expected_max = None
    ratio = None
    if observed is not None and expected_max is not None and expected_max != 0:
        ratio = observed / expected_max
    warnings = list(_profile_warnings(resolutions))
    if profiles and not usable:
        warnings.append(
            warning(
                "PROFILE_CURRENCY_OR_RANGE_MISMATCH",
                "Expected activity is incomplete or does not match the scoped currency.",
            )
        )
    return OperationOutput(
        values=(
            decimal("activity_vs_expected", ratio, unit="ratio_to_expected_max"),
            decimal(
                "expected_activity_min",
                expected_min,
                unit=money_unit(context.currency),
            ),
            decimal(
                "expected_activity_max",
                expected_max,
                unit=money_unit(context.currency),
            ),
        ),
        denominators=(
            denominator("sample_size", len(context.transactions), "transactions"),
            denominator("profile_count", len(profiles), "profiles"),
        ),
        warnings=tuple(warnings),
    )


def income_to_volume_ratio(context: OperationContext) -> OperationOutput:
    resolutions = _profiles(context)
    profiles = tuple(item.profile for item in resolutions if item.profile is not None)
    observed = scoped_money_total(context)
    annual_income = Decimal(0)
    usable = bool(profiles) and len(profiles) == len(resolutions) and context.currency is not None
    for profile in profiles:
        if (
            profile.declared_annual_income_minor is None
            or profile.income_currency != context.currency
        ):
            usable = False
            break
        annual_income += Decimal(profile.declared_annual_income_minor)
    prorated_income = annual_income * _window_days(context) / YEAR_DAYS if usable else None
    ratio = None
    if observed is not None and prorated_income is not None and prorated_income != 0:
        ratio = observed / prorated_income
    warnings = list(_profile_warnings(resolutions))
    if profiles and not usable:
        warnings.append(
            warning(
                "INCOME_UNAVAILABLE_OR_CURRENCY_MISMATCH",
                "Declared numeric income is unavailable or does not match the scoped currency.",
            )
        )
    return OperationOutput(
        values=(decimal("income_to_volume_ratio", ratio, unit="volume/income"),),
        denominators=(
            denominator(
                "prorated_declared_income",
                prorated_income or Decimal(0),
                money_unit(context.currency) or "minor_units",
            ),
            denominator("profile_count", len(profiles), "profiles"),
        ),
        warnings=tuple(warnings),
    )


def account_tenure_days(context: OperationContext) -> OperationOutput:
    repository = AccountRepository(context.session)
    account_ids = context.account_ids()
    collected: list[int] = []
    future_opened = False
    for account_id in account_ids:
        try:
            tenure = repository.account_tenure_days(account_id, as_of=context.request.as_of)
        except ValueError:
            future_opened = True
            continue
        if tenure is not None:
            collected.append(tenure)
    tenures = tuple(collected)
    value = min(tenures) if tenures else None
    warning_items: list[FeatureWarning] = []
    if len(tenures) != len(account_ids) or not account_ids:
        warning_items.append(
            warning(
                "ACCOUNT_DATA_MISSING",
                "Tenure is unavailable for one or more explicitly scoped accounts.",
            )
        )
    if future_opened:
        warning_items.append(
            warning(
                "ACCOUNT_NOT_OPEN_AS_OF",
                "One or more scoped accounts were not open at the requested as_of.",
            )
        )
    return OperationOutput(
        values=(integer("account_tenure_days", value, unit="days"),),
        denominators=(
            denominator("account_count", len(account_ids), "accounts"),
            denominator("accounts_with_tenure", len(tenures), "accounts"),
        ),
        warnings=tuple(warning_items),
    )


def profile_completeness(context: OperationContext) -> OperationOutput:
    resolutions = _profiles(context)
    profiles = tuple(item.profile for item in resolutions if item.profile is not None)
    scores: list[Decimal] = []
    for profile in profiles:
        dimensions = (
            profile.occupation_or_industry is not None,
            profile.declared_annual_income_minor is not None
            or profile.declared_revenue_band is not None,
            profile.income_currency is not None,
            profile.expected_monthly_volume_min_minor is not None,
            profile.expected_monthly_volume_max_minor is not None,
            profile.volume_currency is not None,
            profile.kyc_risk_rating is not None,
        )
        scores.append(Decimal(sum(dimensions)) / Decimal(len(dimensions)))
    score = sum(scores, Decimal(0)) / Decimal(len(scores)) if scores else None
    return OperationOutput(
        values=(decimal("profile_completeness", score, unit="ratio"),),
        denominators=(
            denominator("profile_count", len(profiles), "profiles"),
            denominator("profile_fields", 7, "fields_per_profile"),
        ),
        warnings=_profile_warnings(resolutions),
    )


def data_sufficiency(context: OperationContext) -> OperationOutput:
    policy = context.policy.data_sufficiency
    midpoint = (
        context.scope.start_inclusive
        + (context.scope.end_exclusive - context.scope.start_inclusive) / 2
    )
    baseline_count = len(context.window_transactions(context.scope.start_inclusive, midpoint))
    history_days = _window_days(context)
    transaction_ok = len(context.transactions) >= policy.minimum_transactions
    history_ok = history_days >= Decimal(policy.minimum_history_days)
    baseline_ok = baseline_count >= policy.minimum_baseline_transactions
    sufficient = transaction_ok and history_ok and baseline_ok
    warnings: tuple[FeatureWarning, ...] = ()
    if not sufficient:
        warnings = (
            warning(
                "INSUFFICIENT_DATA",
                "One or more shared data-sufficiency policy requirements were not met.",
            ),
        )
    return OperationOutput(
        values=(
            boolean("data_sufficiency", sufficient),
            boolean("transaction_sample_sufficient", transaction_ok),
            boolean("history_sufficient", history_ok),
            boolean("baseline_sufficient", baseline_ok),
            decimal("history_days", history_days, unit="days"),
        ),
        denominators=(
            denominator("sample_size", len(context.transactions), "transactions"),
            denominator("baseline_sample_size", baseline_count, "transactions"),
            denominator("minimum_transactions", policy.minimum_transactions, "transactions"),
            denominator("minimum_history_days", policy.minimum_history_days, "days"),
            denominator(
                "minimum_baseline_transactions",
                policy.minimum_baseline_transactions,
                "transactions",
            ),
        ),
        warnings=warnings,
    )


OPERATIONS = {
    "activity_vs_expected": activity_vs_expected,
    "income_to_volume_ratio": income_to_volume_ratio,
    "account_tenure_days": account_tenure_days,
    "profile_completeness": profile_completeness,
    "data_sufficiency": data_sufficiency,
}
