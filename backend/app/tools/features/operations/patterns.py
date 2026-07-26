"""Policy-aware transaction pattern and distinct-count operations."""

from datetime import timedelta
from decimal import Decimal

from backend.app.data.models import Transaction
from backend.app.domain.enums import TransactionDirection
from backend.app.domain.features import FeatureWarning
from backend.app.tools.features.operations.common import (
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


def _cash_deposits(context: OperationContext) -> tuple[Transaction, ...]:
    return tuple(
        item
        for item in context.transactions
        if item.transaction_type == "cash_deposit"
        and item.direction == TransactionDirection.CREDIT.value
    )


def cash_deposit_count(context: OperationContext) -> OperationOutput:
    rows = _cash_deposits(context)
    return OperationOutput(
        values=(integer("cash_deposit_count", len(rows), unit="transactions"),),
        denominators=(denominator("sample_size", len(context.transactions), "transactions"),),
    )


def cash_deposit_sum(context: OperationContext) -> OperationOutput:
    rows = _cash_deposits(context)
    return OperationOutput(
        values=(
            decimal(
                "cash_deposit_sum",
                scoped_money_total(context, rows),
                unit=money_unit(context.currency),
            ),
        ),
        denominators=(
            denominator("cash_deposit_sample_size", len(rows), "transactions"),
            denominator("sample_size", len(context.transactions), "transactions"),
        ),
        warnings=money_warning(context),
    )


def _subthreshold(context: OperationContext) -> tuple[Transaction, ...]:
    if context.currency != context.policy.currency:
        return ()
    threshold = Decimal(context.policy.reporting_threshold_minor)
    lower = threshold * Decimal(str(context.policy.structuring.lower_bound_ratio))
    upper = threshold * Decimal(str(context.policy.structuring.upper_bound_ratio))
    return tuple(
        item for item in _cash_deposits(context) if lower <= Decimal(item.amount_minor) <= upper
    )


def _policy_currency_warnings(context: OperationContext) -> tuple[FeatureWarning, ...]:
    if context.transactions and context.currency != context.policy.currency:
        return (
            warning(
                "POLICY_CURRENCY_MISMATCH",
                "The scoped currency does not match the reporting-threshold policy currency.",
            ),
        )
    return ()


def subthreshold_count(context: OperationContext) -> OperationOutput:
    rows = _subthreshold(context)
    return OperationOutput(
        values=(integer("subthreshold_count", len(rows), unit="transactions"),),
        denominators=(
            denominator(
                "reporting_threshold",
                Decimal(context.policy.reporting_threshold_minor),
                f"{context.policy.currency}_minor",
            ),
            denominator("sample_size", len(context.transactions), "transactions"),
        ),
        warnings=_policy_currency_warnings(context),
    )


def subthreshold_total(context: OperationContext) -> OperationOutput:
    rows = _subthreshold(context)
    value = (
        sum((Decimal(item.amount_minor) for item in rows), Decimal(0))
        if context.currency == context.policy.currency
        else None
    )
    return OperationOutput(
        values=(
            decimal(
                "subthreshold_total",
                value,
                unit=f"{context.policy.currency}_minor",
            ),
        ),
        denominators=(
            denominator("subthreshold_sample_size", len(rows), "transactions"),
            denominator(
                "reporting_threshold",
                Decimal(context.policy.reporting_threshold_minor),
                f"{context.policy.currency}_minor",
            ),
        ),
        warnings=_policy_currency_warnings(context),
    )


def round_number_ratio(context: OperationContext) -> OperationOutput:
    increment = context.policy.round_numbers.rounding_increment_minor
    round_count = sum(item.amount_minor % increment == 0 for item in context.transactions)
    ratio = (
        Decimal(round_count) / Decimal(len(context.transactions)) if context.transactions else None
    )
    warnings: tuple[FeatureWarning, ...] = ()
    if not context.transactions:
        warnings = (
            warning(
                "ZERO_DENOMINATOR",
                "Round-number ratio is unavailable because the scoped sample is empty.",
            ),
        )
    return OperationOutput(
        values=(decimal("round_number_ratio", ratio, unit="ratio"),),
        denominators=(
            denominator("round_number_count", round_count, "transactions"),
            denominator("sample_size", len(context.transactions), "transactions"),
        ),
        warnings=warnings,
    )


def _rapid_cash_out(context: OperationContext) -> tuple[Decimal | None, Decimal | None, int, int]:
    if context.currency is None:
        return None, None, 0, 0
    minimum = context.policy.rapid_cash_out.minimum_inflow_minor
    window = timedelta(minutes=context.policy.rapid_cash_out.window_minutes)
    inflows = tuple(
        item
        for item in context.transactions
        if item.direction == TransactionDirection.CREDIT.value and item.amount_minor >= minimum
    )
    matched_outflows: list[Transaction] = []
    elapsed: list[Decimal] = []
    for outflow in context.transactions:
        if outflow.direction != TransactionDirection.DEBIT.value:
            continue
        preceding = tuple(
            inflow
            for inflow in inflows
            if inflow.account_id == outflow.account_id
            and inflow.occurred_at <= outflow.occurred_at
            and outflow.occurred_at - inflow.occurred_at <= window
        )
        if preceding:
            nearest = max(preceding, key=lambda item: (item.occurred_at, item.transaction_id))
            matched_outflows.append(outflow)
            duration = outflow.occurred_at - nearest.occurred_at
            seconds = Decimal(duration.days * 86400 + duration.seconds) + (
                Decimal(duration.microseconds) / Decimal(1_000_000)
            )
            elapsed.append(seconds / Decimal(60))
    inflow_total = sum((Decimal(item.amount_minor) for item in inflows), Decimal(0))
    outflow_total = sum((Decimal(item.amount_minor) for item in matched_outflows), Decimal(0))
    ratio = outflow_total / inflow_total if inflow_total else None
    minimum_elapsed = min(elapsed) if elapsed else None
    return ratio, minimum_elapsed, len(inflows), len(matched_outflows)


def rapid_cash_out_ratio(context: OperationContext) -> OperationOutput:
    ratio, _, inflow_count, outflow_count = _rapid_cash_out(context)
    warnings = list(money_warning(context))
    if inflow_count == 0:
        warnings.append(
            warning(
                "NO_QUALIFYING_INFLOW",
                "No policy-qualifying inflow exists in the explicit feature window.",
            )
        )
    return OperationOutput(
        values=(decimal("rapid_cash_out_ratio", ratio, unit="ratio"),),
        denominators=(
            denominator("qualifying_inflow_count", inflow_count, "transactions"),
            denominator("matched_outflow_count", outflow_count, "transactions"),
        ),
        warnings=tuple(warnings),
    )


def rapid_cash_out_elapsed_time(context: OperationContext) -> OperationOutput:
    _, elapsed, inflow_count, outflow_count = _rapid_cash_out(context)
    warnings: tuple[FeatureWarning, ...] = ()
    if outflow_count == 0:
        warnings = (
            warning(
                "NO_MATCHED_CASH_OUT",
                "No debit followed a qualifying inflow within the policy window.",
            ),
        )
    return OperationOutput(
        values=(decimal("rapid_cash_out_elapsed_time", elapsed, unit="minutes"),),
        denominators=(
            denominator("qualifying_inflow_count", inflow_count, "transactions"),
            denominator("matched_outflow_count", outflow_count, "transactions"),
        ),
        warnings=warnings,
    )


def _distinct(
    context: OperationContext,
    *,
    name: str,
    attribute: str,
) -> OperationOutput:
    values = {
        value for item in context.transactions if (value := getattr(item, attribute)) is not None
    }
    missing = sum(getattr(item, attribute) is None for item in context.transactions)
    warnings: tuple[FeatureWarning, ...] = ()
    if missing:
        warnings = (
            warning(
                "MISSING_DIMENSION_VALUES",
                f"{missing} scoped transactions have no {attribute}.",
            ),
        )
    return OperationOutput(
        values=(integer(name, len(values), unit="distinct"),),
        denominators=(
            denominator("sample_size", len(context.transactions), "transactions"),
            denominator("non_missing_values", len(context.transactions) - missing, "transactions"),
        ),
        warnings=warnings,
    )


def distinct_counterparties(context: OperationContext) -> OperationOutput:
    return _distinct(context, name="distinct_counterparties", attribute="counterparty_id")


def distinct_accounts(context: OperationContext) -> OperationOutput:
    return _distinct(context, name="distinct_accounts", attribute="account_id")


def distinct_devices(context: OperationContext) -> OperationOutput:
    return _distinct(context, name="distinct_devices", attribute="device_id")


def distinct_countries(context: OperationContext) -> OperationOutput:
    return _distinct(context, name="distinct_countries", attribute="country")


OPERATIONS = {
    "cash_deposit_count": cash_deposit_count,
    "cash_deposit_sum": cash_deposit_sum,
    "subthreshold_count": subthreshold_count,
    "subthreshold_total": subthreshold_total,
    "round_number_ratio": round_number_ratio,
    "rapid_cash_out_ratio": rapid_cash_out_ratio,
    "rapid_cash_out_elapsed_time": rapid_cash_out_elapsed_time,
    "distinct_counterparties": distinct_counterparties,
    "distinct_accounts": distinct_accounts,
    "distinct_devices": distinct_devices,
    "distinct_countries": distinct_countries,
}
