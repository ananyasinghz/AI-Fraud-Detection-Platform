"""Deterministic safe plan fallback when Ollama is off or validation fails."""

from __future__ import annotations

from typing import assert_never

from backend.app.domain.enums import IntentType, ToolName
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.nlu import templates


def safe_template_for_intent(
    parsed: ParsedIntent,
    *,
    planner_version: str,
) -> ValidatedPlan | None:
    """Map known intents to Phase 5 templates or a minimal safe plan."""
    filters = parsed.filters
    intent = parsed.intent

    if intent is IntentType.SIMPLE_LOOKUP:
        if filters.amount_min is not None and not filters.customer_ids:
            plan = templates.plan_sql_amount_lookup(filters)
        elif filters.customer_ids:
            plan = templates.plan_simple_customer_lookup(parsed)
        elif filters.transaction_ids:
            plan = _plan_transaction_lookup(parsed, planner_version=planner_version)
        else:
            return None
        return _retag(plan, planner_version)

    if intent is IntentType.THRESHOLD_AGGREGATION:
        return _retag(templates.plan_threshold_aggregation(filters), planner_version)

    if intent is IntentType.FEATURE_COMPARISON:
        if not filters.customer_ids:
            return None
        return _retag(templates.plan_feature_only(parsed), planner_version)

    if intent is IntentType.PATTERN_SEARCH:
        if not filters.customer_ids:
            return None
        return _retag(templates.plan_pattern_search(parsed), planner_version)

    if intent is IntentType.ENTITY_INVESTIGATION:
        if not filters.customer_ids:
            return None
        return _retag(templates.plan_entity_investigation(parsed), planner_version)

    if intent is IntentType.TRANSACTION_SCORING:
        if not filters.transaction_ids:
            return None
        return _retag(templates.plan_transaction_scoring(parsed), planner_version)

    if intent is IntentType.BROAD_EXPLORATION:
        return _retag(templates.plan_broad_exploration(), planner_version)

    if intent is IntentType.EXPLANATION_REQUEST:
        if not filters.customer_ids and not filters.transaction_ids:
            return None
        return _retag(templates.plan_explanation_request(parsed), planner_version)

    assert_never(intent)


def _retag(plan: ValidatedPlan, planner_version: str) -> ValidatedPlan:
    return plan.model_copy(update={"planner_version": planner_version})


def _plan_transaction_lookup(parsed: ParsedIntent, *, planner_version: str) -> ValidatedPlan:
    txn_id = parsed.filters.transaction_ids[0]
    return ValidatedPlan(
        strategy="simple_transaction_lookup",
        planner_version=planner_version,
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_transaction",
                parameters={"transaction_id": txn_id},
                reason="simple transaction lookup",
            )
        ],
    )
