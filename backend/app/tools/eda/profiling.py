"""EDA profiling that emits real ChartSpec objects without label leakage."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

from pydantic import JsonValue

from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import CustomerRepository, TransactionRepository
from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import ChartType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result


def handle_eda(context: ToolContext, operation: str, parameters: dict[str, Any]) -> ToolResult:
    timer = Timer()
    provenance = ToolProvenance(
        source="eda",
        query_or_version="eda.v1",
        policy_version=context.policy.version,
    )
    scope = QueryScope.from_filters(context.filters, as_of=context.as_of)
    transactions = TransactionRepository(context.session).list_scoped(scope)

    if operation == "cohort_profile":
        return _cohort_profile(context, operation, timer, provenance, scope, transactions)
    if operation == "volume_over_time":
        return _volume_over_time(context, operation, timer, provenance, transactions)
    if operation == "missingness_quality":
        return _missingness_quality(context, operation, timer, provenance, transactions)
    if operation == "amount_distribution":
        return _amount_distribution(context, operation, timer, provenance, transactions)
    if operation == "class_balance":
        return _class_balance(context, operation, parameters, timer, provenance, transactions)
    raise ValueError(f"unknown eda operation: {operation}")


def _cohort_profile(
    context: ToolContext,
    operation: str,
    timer: Timer,
    provenance: ToolProvenance,
    scope: QueryScope,
    transactions: list[Any],
) -> ToolResult:
    amounts = [item.amount_minor for item in transactions]
    types = Counter(item.transaction_type for item in transactions)
    missing_country = sum(item.country is None for item in transactions)
    customer_ids = sorted({item.customer_id for item in transactions})
    completeness_scores: list[float] = []
    segments: Counter[str] = Counter()
    for customer_id in customer_ids:
        resolution = CustomerRepository(context.session).get_profile_as_of(
            customer_id,
            context.as_of,
        )
        profile = resolution.profile
        if profile is None:
            completeness_scores.append(0.0)
            continue
        segments[profile.segment] += 1
        dims = (
            profile.occupation_or_industry is not None,
            profile.declared_annual_income_minor is not None
            or profile.declared_revenue_band is not None,
            profile.expected_monthly_volume_max_minor is not None,
            profile.kyc_risk_rating is not None,
        )
        completeness_scores.append(sum(dims) / len(dims))
    chart = ChartSpec(
        chart_id="txn-type-bar",
        chart_type=ChartType.BAR,
        title="Transaction types in scope",
        data={
            "labels": list(types.keys()),
            "values": [types[key] for key in types],
        },
        x_label="transaction_type",
        y_label="count",
        evidence_refs=["ev.eda.types"],
    )
    return make_result(
        tool=ToolName.EDA,
        operation=operation,
        status=ToolStatus.SUCCESS if transactions or scope.is_empty else ToolStatus.PARTIAL,
        scope=context.filters,
        data={
            "transaction_count": len(transactions),
            "customer_count": len(customer_ids),
            "amount_min_minor": min(amounts) if amounts else None,
            "amount_max_minor": max(amounts) if amounts else None,
            "amount_mean_minor": (sum(amounts) / len(amounts)) if amounts else None,
            "missing_country_count": missing_country,
            "profile_completeness_mean": (
                sum(completeness_scores) / len(completeness_scores) if completeness_scores else None
            ),
            "segment_counts": dict(segments),
            "charts": [chart.model_dump(mode="json")],
        },
        warnings=(["empty scope"] if scope.is_empty else []),
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _volume_over_time(
    context: ToolContext,
    operation: str,
    timer: Timer,
    provenance: ToolProvenance,
    transactions: list[Any],
) -> ToolResult:
    by_day: Counter[str] = Counter()
    for item in transactions:
        by_day[item.occurred_at.date().isoformat()] += 1
    labels = sorted(by_day)
    chart = ChartSpec(
        chart_id="volume-over-time",
        chart_type=ChartType.LINE,
        title="Transaction volume over time",
        data=cast(
            dict[str, JsonValue],
            {"labels": labels, "values": [by_day[label] for label in labels]},
        ),
        x_label="utc_day",
        y_label="transactions",
        evidence_refs=["ev.eda.volume"],
    )
    return make_result(
        tool=ToolName.EDA,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            "days": len(labels),
            "charts": [chart.model_dump(mode="json")],
        },
        warnings=(["no transactions in scope"] if not transactions else []),
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _missingness_quality(
    context: ToolContext,
    operation: str,
    timer: Timer,
    provenance: ToolProvenance,
    transactions: list[Any],
) -> ToolResult:
    total = len(transactions)
    fields = {
        "country": sum(item.country is None for item in transactions),
        "counterparty_id": sum(item.counterparty_id is None for item in transactions),
        "device_id": sum(item.device_id is None for item in transactions),
        "posted_at": sum(item.posted_at is None for item in transactions),
    }
    chart = ChartSpec(
        chart_id="missingness-bar",
        chart_type=ChartType.BAR,
        title="Missing optional transaction fields",
        data={"labels": list(fields.keys()), "values": list(fields.values())},
        x_label="field",
        y_label="missing_count",
        evidence_refs=["ev.eda.missingness"],
    )
    return make_result(
        tool=ToolName.EDA,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            "transaction_count": total,
            "missing_counts": fields,
            "charts": [chart.model_dump(mode="json")],
        },
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _amount_distribution(
    context: ToolContext,
    operation: str,
    timer: Timer,
    provenance: ToolProvenance,
    transactions: list[Any],
) -> ToolResult:
    amounts = sorted(item.amount_minor for item in transactions)
    if not amounts:
        return make_result(
            tool=ToolName.EDA,
            operation=operation,
            status=ToolStatus.PARTIAL,
            scope=context.filters,
            data={"charts": []},
            warnings=["no amounts in scope"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )
    # Fixed-width histogram buckets in minor units.
    bucket_width = max(1, (max(amounts) - min(amounts)) // 5 or 1)
    buckets: Counter[str] = Counter()
    for amount in amounts:
        start = (amount // bucket_width) * bucket_width
        label = f"{start}-{start + bucket_width}"
        buckets[label] += 1
    labels = sorted(buckets, key=lambda item: int(item.split("-", 1)[0]))
    chart = ChartSpec(
        chart_id="amount-histogram",
        chart_type=ChartType.HISTOGRAM,
        title="Amount distribution (minor units)",
        data=cast(
            dict[str, JsonValue],
            {"labels": labels, "values": [buckets[label] for label in labels]},
        ),
        x_label="amount_minor_bucket",
        y_label="count",
        evidence_refs=["ev.eda.amounts"],
    )
    return make_result(
        tool=ToolName.EDA,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            "count": len(amounts),
            "min_minor": amounts[0],
            "max_minor": amounts[-1],
            "median_minor": amounts[len(amounts) // 2],
            "charts": [chart.model_dump(mode="json")],
        },
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _class_balance(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
    timer: Timer,
    provenance: ToolProvenance,
    transactions: list[Any],
) -> ToolResult:
    allow_labels = bool(parameters.get("allow_labels", False))
    if not allow_labels:
        return make_result(
            tool=ToolName.EDA,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["LABELS_NOT_ALLOWLISTED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )
    # Runtime tables do not store Class/scenario labels. Report data_source mix only.
    sources = Counter(item.data_source for item in transactions)
    chart = ChartSpec(
        chart_id="data-source-balance",
        chart_type=ChartType.BAR,
        title="Data source mix in scope",
        data={"labels": list(sources.keys()), "values": [sources[key] for key in sources]},
        x_label="data_source",
        y_label="count",
        evidence_refs=["ev.eda.sources"],
    )
    return make_result(
        tool=ToolName.EDA,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            "note": "Held-out scenario and ULB fraud labels are unavailable in runtime tables",
            "data_source_counts": dict(sources),
            "charts": [chart.model_dump(mode="json")],
        },
        warnings=["CLASS_LABELS_UNAVAILABLE_AT_RUNTIME"],
        duration_ms=timer.ms(),
        provenance=provenance,
    )
