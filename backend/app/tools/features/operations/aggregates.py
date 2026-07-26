"""Core transaction aggregation and rate operations."""

from datetime import timedelta
from decimal import Decimal

from backend.app.tools.features.operations.common import (
    INSUFFICIENT_DATA,
    OperationContext,
    OperationOutput,
    decimal,
    denominator,
    integer,
    money_unit,
    money_warning,
    scoped_money_total,
    warning,
)


def transaction_count(context: OperationContext) -> OperationOutput:
    return OperationOutput(
        values=(integer("transaction_count", len(context.transactions), unit="transactions"),),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
    )


def transaction_total(context: OperationContext) -> OperationOutput:
    return OperationOutput(
        values=(
            decimal(
                "transaction_total",
                scoped_money_total(context),
                unit=money_unit(context.currency),
            ),
        ),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
        warnings=money_warning(context),
    )


def rolling_count(context: OperationContext) -> OperationOutput:
    return OperationOutput(
        values=(integer("rolling_count", len(context.transactions), unit="transactions"),),
        denominators=(denominator("window_seconds", _window_seconds(context), "seconds"),),
    )


def rolling_sum(context: OperationContext) -> OperationOutput:
    return OperationOutput(
        values=(
            decimal("rolling_sum", scoped_money_total(context), unit=money_unit(context.currency)),
        ),
        denominators=(
            denominator("sample_size", len(context.transactions), "transactions"),
            denominator("window_seconds", _window_seconds(context), "seconds"),
        ),
        warnings=money_warning(context),
    )


def average_amount(context: OperationContext) -> OperationOutput:
    total = scoped_money_total(context)
    value = (
        total / Decimal(len(context.transactions))
        if total is not None and context.transactions
        else None
    )
    warnings = list(money_warning(context))
    if not context.transactions:
        warnings.append(INSUFFICIENT_DATA)
    return OperationOutput(
        values=(decimal("average_amount", value, unit=money_unit(context.currency)),),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
        warnings=tuple(warnings),
    )


def median_amount(context: OperationContext) -> OperationOutput:
    amounts = sorted(Decimal(item.amount_minor) for item in context.transactions)
    value: Decimal | None = None
    if amounts and context.currency is not None:
        middle = len(amounts) // 2
        value = (
            amounts[middle]
            if len(amounts) % 2
            else (amounts[middle - 1] + amounts[middle]) / Decimal(2)
        )
    warnings = list(money_warning(context))
    if not amounts:
        warnings.append(INSUFFICIENT_DATA)
    return OperationOutput(
        values=(decimal("median_amount", value, unit=money_unit(context.currency)),),
        denominators=(denominator("sample_size", len(amounts), "transactions"),),
        warnings=tuple(warnings),
    )


def maximum_amount(context: OperationContext) -> OperationOutput:
    value = (
        Decimal(max(item.amount_minor for item in context.transactions))
        if context.transactions and context.currency is not None
        else None
    )
    warnings = list(money_warning(context))
    if not context.transactions:
        warnings.append(INSUFFICIENT_DATA)
    return OperationOutput(
        values=(decimal("maximum_amount", value, unit=money_unit(context.currency)),),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
        warnings=tuple(warnings),
    )


def amount_deviation(context: OperationContext) -> OperationOutput:
    """Return deterministic population standard deviation in minor units."""
    value: Decimal | None = None
    if context.transactions and context.currency is not None:
        amounts = tuple(Decimal(item.amount_minor) for item in context.transactions)
        mean = sum(amounts, Decimal(0)) / Decimal(len(amounts))
        variance = sum(((item - mean) ** 2 for item in amounts), Decimal(0)) / Decimal(len(amounts))
        value = variance.sqrt()
    warnings = list(money_warning(context))
    if not context.transactions:
        warnings.append(INSUFFICIENT_DATA)
    return OperationOutput(
        values=(decimal("amount_deviation", value, unit=money_unit(context.currency)),),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
        warnings=tuple(warnings),
    )


def period_baseline_deviation(context: OperationContext) -> OperationOutput:
    """Compare the latter half of the explicit window with its trailing first half."""
    duration = context.scope.end_exclusive - context.scope.start_inclusive
    midpoint = context.scope.start_inclusive + duration / 2
    baseline = context.window_transactions(context.scope.start_inclusive, midpoint)
    current = context.window_transactions(midpoint, context.scope.end_exclusive)
    baseline_total = scoped_money_total(context, baseline)
    current_total = scoped_money_total(context, current)
    absolute: Decimal | None = None
    ratio: Decimal | None = None
    if baseline_total is not None and current_total is not None:
        absolute = current_total - baseline_total
        if baseline_total != 0:
            ratio = current_total / baseline_total
    warnings = list(money_warning(context))
    if not baseline:
        warnings.append(
            warning(
                "INSUFFICIENT_BASELINE",
                "The first half of the explicit feature window contains no baseline observations.",
            )
        )
    return OperationOutput(
        values=(
            decimal(
                "period_baseline_deviation",
                absolute,
                unit=money_unit(context.currency),
            ),
            decimal("period_baseline_ratio", ratio, unit="ratio"),
        ),
        denominators=(
            denominator("current_sample_size", len(current), "transactions"),
            denominator("baseline_sample_size", len(baseline), "transactions"),
            denominator("baseline_total", baseline_total or Decimal(0), "minor_units"),
        ),
        warnings=tuple(warnings),
    )


def transactions_per_hour(context: OperationContext) -> OperationOutput:
    hours = _window_seconds(context) / Decimal(3600)
    value = Decimal(len(context.transactions)) / hours
    return OperationOutput(
        values=(decimal("transactions_per_hour", value, unit="transactions/hour"),),
        denominators=(denominator("window_hours", hours, "hours"),),
    )


def transactions_per_day(context: OperationContext) -> OperationOutput:
    days = _window_seconds(context) / Decimal(86400)
    value = Decimal(len(context.transactions)) / days
    return OperationOutput(
        values=(decimal("transactions_per_day", value, unit="transactions/day"),),
        denominators=(denominator("window_days", days, "days"),),
    )


def _window_seconds(context: OperationContext) -> Decimal:
    duration: timedelta = context.scope.end_exclusive - context.scope.start_inclusive
    return Decimal(duration.days * 86400 + duration.seconds) + (
        Decimal(duration.microseconds) / Decimal(1_000_000)
    )


OPERATIONS = {
    "transaction_count": transaction_count,
    "transaction_total": transaction_total,
    "rolling_count": rolling_count,
    "rolling_sum": rolling_sum,
    "average_amount": average_amount,
    "median_amount": median_amount,
    "maximum_amount": maximum_amount,
    "amount_deviation": amount_deviation,
    "period_baseline_deviation": period_baseline_deviation,
    "transactions_per_hour": transactions_per_hour,
    "transactions_per_day": transactions_per_day,
}
