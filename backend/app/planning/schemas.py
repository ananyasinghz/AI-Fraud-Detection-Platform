"""Tool capability catalog for the dynamic planner (schemas only, no callables)."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.domain.enums import ToolName

# Phase 7 whitelist — implemented tools only (no Phase 8).
PLANNER_WHITELIST: frozenset[ToolName] = frozenset(
    {
        ToolName.SQL_LOOKUP,
        ToolName.FEATURE_ENGINEERING,
        ToolName.EDA,
        ToolName.ANOMALY_DETECTION,
        ToolName.GRAPH_ANALYSIS,
        ToolName.RETRIEVAL,
    }
)

BLOCKED_TOOLS: frozenset[ToolName] = frozenset(
    {
        ToolName.RISK_CLASSIFICATION,
        ToolName.VERIFICATION,
        ToolName.ESCALATION,
        ToolName.EXPLANATION,
    }
)

ALLOWED_OPERATIONS: dict[ToolName, frozenset[str]] = {
    ToolName.SQL_LOOKUP: frozenset({"get_customer", "get_transaction", "list_transactions"}),
    ToolName.FEATURE_ENGINEERING: frozenset({"compute_feature", "run_operation"}),
    ToolName.EDA: frozenset(
        {
            "cohort_profile",
            "volume_over_time",
            "missingness_quality",
            "amount_distribution",
            "class_balance",
        }
    ),
    ToolName.ANOMALY_DETECTION: frozenset({"detect"}),
    ToolName.GRAPH_ANALYSIS: frozenset(
        {
            "shared_device",
            "circular_transfers",
            "two_hop_exposure",
            "connected_accounts",
        }
    ),
    ToolName.RETRIEVAL: frozenset({"search_policy"}),
}


@dataclass(frozen=True)
class ToolCapability:
    tool: ToolName
    operations: frozenset[str]
    param_hints: str
    when_to_use: str


def build_capability_catalog() -> tuple[ToolCapability, ...]:
    """Static capability descriptions for planner prompts (not live dispatch)."""
    return (
        ToolCapability(
            tool=ToolName.SQL_LOOKUP,
            operations=ALLOWED_OPERATIONS[ToolName.SQL_LOOKUP],
            param_hints=(
                "get_customer: {customer_id}; get_transaction: {transaction_id}; "
                "list_transactions: {} (filters come from request scope)"
            ),
            when_to_use="Entity or amount-threshold lookups; listing scoped transactions.",
        ),
        ToolCapability(
            tool=ToolName.FEATURE_ENGINEERING,
            operations=ALLOWED_OPERATIONS[ToolName.FEATURE_ENGINEERING],
            param_hints=(
                "compute_feature: {feature_operation, entity_ids[], window_days, currency?}"
            ),
            when_to_use="Aggregates, baselines, structuring/subthreshold features for entities.",
        ),
        ToolCapability(
            tool=ToolName.EDA,
            operations=ALLOWED_OPERATIONS[ToolName.EDA],
            param_hints="cohort_profile|volume_over_time|...: {} for dataset-wide exploration",
            when_to_use="Broad dataset exploration only; never for single-customer lookups.",
        ),
        ToolCapability(
            tool=ToolName.ANOMALY_DETECTION,
            operations=ALLOWED_OPERATIONS[ToolName.ANOMALY_DETECTION],
            param_hints="detect: {mode: rules_only|ml_only|hybrid, entity_id?|transaction_id?}",
            when_to_use="Rules/ML anomaly signals after scoped features or transaction load.",
        ),
        ToolCapability(
            tool=ToolName.GRAPH_ANALYSIS,
            operations=ALLOWED_OPERATIONS[ToolName.GRAPH_ANALYSIS],
            param_hints=(
                "shared_device|circular_transfers|two_hop_exposure|connected_accounts: "
                "{customer_id?|account_id?}"
            ),
            when_to_use=(
                "Shared-device, circular transfer, or multi-hop exposure questions; "
                "requires entity/cohort scope."
            ),
        ),
        ToolCapability(
            tool=ToolName.RETRIEVAL,
            operations=ALLOWED_OPERATIONS[ToolName.RETRIEVAL],
            param_hints="search_policy: {query, top_k?}",
            when_to_use=(
                "Optional policy-context snippets for reviewers; never replaces evidence "
                "and never states legal conclusions."
            ),
        ),
    )


def catalog_prompt_block() -> str:
    lines: list[str] = ["Allowed tools and operations:"]
    for item in build_capability_catalog():
        ops = ", ".join(sorted(item.operations))
        lines.append(f"- {item.tool.value}: ops=[{ops}]")
        lines.append(f"  params: {item.param_hints}")
        lines.append(f"  when: {item.when_to_use}")
    lines.append("Do not select risk_classification, explanation, verification, or escalation.")
    return "\n".join(lines)
