"""Deterministic Python router: ParsedIntent → route + template plan."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from backend.app.domain.enums import IntentType, RouteType, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import ValidatedPlan
from backend.app.nlu import templates


@dataclass(frozen=True)
class RoutingDecision:
    route: RouteType
    filters: NormalizedFilters
    plan: ValidatedPlan | None
    tools_invoked_expected: tuple[ToolName, ...]
    tools_skipped_expected: tuple[ToolName, ...]
    clarification: str | None = None
    needs_planner: bool = False


def _expected_tools(plan: ValidatedPlan) -> tuple[ToolName, ...]:
    seen: list[ToolName] = []
    for step in plan.steps:
        if step.tool not in seen:
            seen.append(step.tool)
    return tuple(seen)


def route_parsed_intent(
    parsed: ParsedIntent,
    *,
    confidence_floor: float,
) -> RoutingDecision:
    """Map validated intent to a deterministic template or clarification."""
    filters = parsed.filters
    low_confidence = parsed.confidence < confidence_floor
    ambiguous = bool(parsed.ambiguities) and low_confidence

    if parsed.intent is IntentType.EXPLANATION_REQUEST:
        if not filters.customer_ids and not filters.transaction_ids:
            return RoutingDecision(
                route=RouteType.FULL_INVESTIGATION,
                filters=filters,
                plan=None,
                tools_invoked_expected=(),
                tools_skipped_expected=(ToolName.EXPLANATION, ToolName.RISK_CLASSIFICATION),
                clarification=(
                    "Explanation requires a customer or transaction id so verified "
                    "evidence can be grounded."
                ),
                needs_planner=False,
            )
        plan = templates.plan_explanation_request(parsed)
        return RoutingDecision(
            route=RouteType.FULL_INVESTIGATION,
            filters=filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA,),
            needs_planner=False,
        )

    if ambiguous and parsed.intent is IntentType.BROAD_EXPLORATION:
        # Do not silently broaden on low-confidence broad asks.
        return RoutingDecision(
            route=RouteType.SIMPLE_LOOKUP,
            filters=NormalizedFilters(
                max_results=filters.max_results,
                currency=filters.currency,
            ),
            plan=None,
            tools_invoked_expected=(),
            tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
            clarification="Query is ambiguous; specify an entity, amount threshold, or pattern.",
            needs_planner=False,
        )

    if parsed.intent is IntentType.SIMPLE_LOOKUP:
        if filters.amount_min is not None and not filters.customer_ids:
            plan = templates.plan_sql_amount_lookup(filters)
            # Ensure default $10k semantics when amount present.
            if filters.amount_min == 0:
                filters = filters.model_copy(update={"amount_min": Decimal("10000")})
            return RoutingDecision(
                route=RouteType.SIMPLE_LOOKUP,
                filters=filters,
                plan=plan,
                tools_invoked_expected=_expected_tools(plan),
                tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
            )
        if filters.customer_ids:
            plan = templates.plan_simple_customer_lookup(parsed)
            return RoutingDecision(
                route=RouteType.SIMPLE_LOOKUP,
                filters=filters,
                plan=plan,
                tools_invoked_expected=_expected_tools(plan),
                tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
            )
        if filters.transaction_ids and not low_confidence:
            # No fixed template for transaction-id lookup; dynamic planner + safe fallback.
            return RoutingDecision(
                route=RouteType.SIMPLE_LOOKUP,
                filters=filters,
                plan=None,
                tools_invoked_expected=(ToolName.SQL_LOOKUP,),
                tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
                needs_planner=True,
            )
        return RoutingDecision(
            route=RouteType.SIMPLE_LOOKUP,
            filters=filters,
            plan=None,
            tools_invoked_expected=(),
            tools_skipped_expected=(),
            clarification="Simple lookup needs a customer id or amount threshold.",
            needs_planner=False,
        )

    if parsed.intent is IntentType.THRESHOLD_AGGREGATION:
        plan = templates.plan_threshold_aggregation(filters)
        return RoutingDecision(
            route=RouteType.FEATURE_ONLY,
            filters=filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
        )

    if parsed.intent is IntentType.FEATURE_COMPARISON:
        if not filters.customer_ids:
            return RoutingDecision(
                route=RouteType.FEATURE_ONLY,
                filters=filters,
                plan=None,
                tools_invoked_expected=(),
                tools_skipped_expected=(ToolName.EDA,),
                clarification="Feature comparison requires a customer id.",
            )
        plan = templates.plan_feature_only(parsed)
        return RoutingDecision(
            route=RouteType.FEATURE_ONLY,
            filters=filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
        )

    if parsed.intent is IntentType.PATTERN_SEARCH:
        plan = templates.plan_pattern_search(parsed)
        # pattern_type is planning metadata, not a SQL/transaction predicate.
        exec_filters = filters.model_copy(update={"pattern_type": None})
        return RoutingDecision(
            route=RouteType.FULL_INVESTIGATION,
            filters=exec_filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA,),
        )

    if parsed.intent is IntentType.ENTITY_INVESTIGATION:
        if not filters.customer_ids:
            return RoutingDecision(
                route=RouteType.FULL_INVESTIGATION,
                filters=filters,
                plan=None,
                tools_invoked_expected=(),
                tools_skipped_expected=(ToolName.EDA,),
                clarification="Entity investigation requires a valid customer id.",
            )
        plan = templates.plan_entity_investigation(parsed)
        return RoutingDecision(
            route=RouteType.FULL_INVESTIGATION,
            filters=filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA,),
        )

    if parsed.intent is IntentType.TRANSACTION_SCORING:
        if not filters.transaction_ids:
            return RoutingDecision(
                route=RouteType.SIMPLE_LOOKUP,
                filters=filters,
                plan=None,
                tools_invoked_expected=(),
                tools_skipped_expected=(),
                clarification="Transaction scoring requires a transaction id.",
            )
        plan = templates.plan_transaction_scoring(parsed)
        return RoutingDecision(
            route=RouteType.FULL_INVESTIGATION,
            filters=filters,
            plan=plan,
            tools_invoked_expected=_expected_tools(plan),
            tools_skipped_expected=(ToolName.EDA,),
        )

    # broad_exploration
    if low_confidence:
        return RoutingDecision(
            route=RouteType.SIMPLE_LOOKUP,
            filters=NormalizedFilters(max_results=filters.max_results),
            plan=None,
            tools_invoked_expected=(),
            tools_skipped_expected=(ToolName.EDA, ToolName.ANOMALY_DETECTION),
            clarification="Low-confidence broad request; refine scope before dataset EDA.",
        )
    plan = templates.plan_broad_exploration()
    return RoutingDecision(
        route=RouteType.FULL_INVESTIGATION,
        filters=filters,
        plan=plan,
        tools_invoked_expected=_expected_tools(plan),
        tools_skipped_expected=(),
    )
