"""Targeted SQL lookup operations over scoped repositories."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import Any

from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import CustomerRepository, TransactionRepository
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result


def handle_sql_lookup(
    context: ToolContext, operation: str, parameters: dict[str, Any]
) -> ToolResult:
    timer = Timer()
    provenance = ToolProvenance(
        source="sql_lookup",
        query_or_version="sql_lookup.v1",
        policy_version=context.policy.version,
    )
    if operation == "get_customer":
        customer_id = str(parameters.get("customer_id", ""))
        customer = CustomerRepository(context.session).get_by_id(customer_id)
        if customer is None:
            return make_result(
                tool=ToolName.SQL_LOOKUP,
                operation=operation,
                status=ToolStatus.SKIPPED,
                scope=context.filters,
                warnings=[f"customer not found: {customer_id}"],
                duration_ms=timer.ms(),
                provenance=provenance,
            )
        return make_result(
            tool=ToolName.SQL_LOOKUP,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={
                "customer_id": customer.customer_id,
                "created_at": customer.created_at.isoformat(),
                "status": customer.status,
            },
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    if operation == "get_transaction":
        transaction_id = str(parameters.get("transaction_id", ""))
        transaction = TransactionRepository(context.session).get_by_id(transaction_id)
        if transaction is None:
            return make_result(
                tool=ToolName.SQL_LOOKUP,
                operation=operation,
                status=ToolStatus.SKIPPED,
                scope=context.filters,
                warnings=[f"transaction not found: {transaction_id}"],
                duration_ms=timer.ms(),
                provenance=provenance,
            )
        return make_result(
            tool=ToolName.SQL_LOOKUP,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data=_transaction_payload(transaction),
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    if operation == "list_transactions":
        scope = QueryScope.from_filters(context.filters, as_of=context.as_of)
        rows = TransactionRepository(context.session).list_scoped(scope)
        return make_result(
            tool=ToolName.SQL_LOOKUP,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={
                "count": len(rows),
                "transactions": [_transaction_payload(item) for item in rows],
                "scope_empty": scope.is_empty,
            },
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    if operation == "count_by_customer":
        minimum_count = int(parameters.get("minimum_count", 10))
        # Aggregation needs a wider page than the default reviewer max_results=100.
        filters = context.filters.model_copy(update={"max_results": 1000})
        scope = QueryScope.from_filters(filters, as_of=context.as_of)
        scope = replace(scope, limit=1000)
        rows = TransactionRepository(context.session).list_scoped(scope)
        counts = Counter(item.customer_id for item in rows)
        matching = [
            {"customer_id": customer_id, "transaction_count": count}
            for customer_id, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
            if count >= minimum_count
        ]
        amount_max = (
            str(context.filters.amount_max) if context.filters.amount_max is not None else None
        )
        return make_result(
            tool=ToolName.SQL_LOOKUP,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={
                "customers": matching,
                "minimum_count": minimum_count,
                "amount_max": amount_max,
                "total_matching": len(matching),
                "scoped_transaction_count": len(rows),
                "scope_empty": scope.is_empty,
                "query_limit_reached": len(rows) >= scope.limit,
            },
            warnings=(["QUERY_LIMIT_REACHED"] if len(rows) >= scope.limit else []),
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    raise ValueError(f"unknown sql_lookup operation: {operation}")


def _transaction_payload(transaction: Any) -> dict[str, Any]:
    return {
        "transaction_id": transaction.transaction_id,
        "customer_id": transaction.customer_id,
        "account_id": transaction.account_id,
        "occurred_at": transaction.occurred_at.isoformat(),
        "amount_minor": transaction.amount_minor,
        "currency": transaction.currency,
        "direction": transaction.direction,
        "transaction_type": transaction.transaction_type,
        "channel": transaction.channel,
        "country": transaction.country,
        "ml_eligible": transaction.ml_eligible,
        "ml_feature_ref": transaction.ml_feature_ref,
        "data_source": transaction.data_source,
    }
