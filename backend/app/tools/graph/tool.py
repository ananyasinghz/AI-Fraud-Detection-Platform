"""Graph-analysis tool wrapping NetworkX relationship queries."""

from __future__ import annotations

from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance
from backend.app.domain.filters import NormalizedFilters
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result
from backend.app.tools.graph.builder import build_relationship_graph
from backend.app.tools.graph.queries import (
    circular_transfers,
    connected_accounts,
    shared_device,
    two_hop_exposure,
)

_OPS = frozenset(
    {
        "shared_device",
        "circular_transfers",
        "two_hop_exposure",
        "connected_accounts",
    }
)


def handle_graph_analysis(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    provenance = ToolProvenance(
        source="graph_analysis",
        query_or_version="graph_analysis.v1",
        policy_version=context.policy.version,
    )
    if not context.settings.graph_enabled:
        return make_result(
            tool=ToolName.GRAPH_ANALYSIS,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["GRAPH_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )
    if operation not in _OPS:
        raise ValueError(f"unknown graph_analysis operation: {operation}")

    filters = _merge_scope(context.filters, parameters)
    allow_unscoped = bool(parameters.get("allow_unscoped", False))
    graph, warnings = build_relationship_graph(
        context.session,
        filters,
        allow_unscoped=allow_unscoped,
    )
    if "EMPTY_GRAPH_SCOPE" in warnings:
        return make_result(
            tool=ToolName.GRAPH_ANALYSIS,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=filters,
            data={"findings": [], "count": 0},
            warnings=warnings,
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    customer_ids = list(filters.customer_ids) or [
        str(parameters[k]) for k in ("customer_id", "entity_id") if parameters.get(k)
    ]
    account_ids = list(filters.account_ids) or [
        str(parameters["account_id"]) for _ in [0] if parameters.get("account_id")
    ]

    if operation == "shared_device":
        data = shared_device(graph, seed_customer_ids=customer_ids or None)
    elif operation == "circular_transfers":
        data = circular_transfers(graph)
    elif operation == "two_hop_exposure":
        data = two_hop_exposure(
            graph,
            seed_account_ids=account_ids or None,
            seed_customer_ids=customer_ids or None,
        )
    else:
        data = connected_accounts(graph, seed_account_ids=account_ids or None)

    return make_result(
        tool=ToolName.GRAPH_ANALYSIS,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=filters,
        data=data,
        warnings=warnings,
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _merge_scope(base: NormalizedFilters, parameters: dict[str, Any]) -> NormalizedFilters:
    customer_ids = list(base.customer_ids)
    account_ids = list(base.account_ids)
    transaction_ids = list(base.transaction_ids)
    if parameters.get("customer_id"):
        customer_ids.append(str(parameters["customer_id"]))
    if parameters.get("entity_id") and parameters.get("entity_type", "customer") == "customer":
        customer_ids.append(str(parameters["entity_id"]))
    if parameters.get("account_id"):
        account_ids.append(str(parameters["account_id"]))
    if parameters.get("customer_ids") and isinstance(parameters["customer_ids"], list):
        customer_ids.extend(str(item) for item in parameters["customer_ids"])
    if parameters.get("account_ids") and isinstance(parameters["account_ids"], list):
        account_ids.extend(str(item) for item in parameters["account_ids"])
    # Dedupe preserving order
    customer_ids = list(dict.fromkeys(customer_ids))
    account_ids = list(dict.fromkeys(account_ids))
    return base.model_copy(
        update={
            "customer_ids": customer_ids,
            "account_ids": account_ids,
            "transaction_ids": transaction_ids,
        }
    )
