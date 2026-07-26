"""Deterministic ValidatedPlan templates owned by the Phase 5 router."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from backend.app.domain.enums import ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import PlanStep, ValidatedPlan


def plan_sql_amount_lookup(filters: NormalizedFilters) -> ValidatedPlan:
    return ValidatedPlan(
        strategy="sql_amount_lookup",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="list_transactions",
                parameters={},
                reason="targeted amount threshold lookup",
            )
        ],
    )


def plan_threshold_aggregation(filters: NormalizedFilters) -> ValidatedPlan:
    entity_ids = list(filters.customer_ids) or ["*"]
    # Feature ops require concrete entity ids; use placeholder that yields empty if unknown.
    concrete = [item for item in entity_ids if item != "*"]
    parameters: dict[str, JsonValue] = {
        "feature_operation": "transaction_count",
        "entity_ids": cast(JsonValue, concrete or ["UNKNOWN"]),
        "window_days": 30,
    }
    if filters.currency:
        parameters["currency"] = filters.currency
    return ValidatedPlan(
        strategy="threshold_aggregation",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="list_transactions",
                parameters={},
                reason="list scoped transactions under threshold",
            ),
            PlanStep(
                step_id="feat1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters=parameters,
                reason="count transactions for threshold comparison",
                depends_on=["sql1"],
            ),
        ],
    )


def plan_feature_only(parsed: ParsedIntent) -> ValidatedPlan:
    customer_ids = list(parsed.filters.customer_ids) or ["UNKNOWN"]
    return ValidatedPlan(
        strategy="feature_only",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="feat1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_total",
                    "entity_ids": cast(JsonValue, customer_ids[:1]),
                    "window_days": 30,
                    "currency": parsed.filters.currency or "USD",
                },
                reason="compare recent spending features",
            )
        ],
    )


def plan_pattern_search(parsed: ParsedIntent) -> ValidatedPlan:
    customer_ids = list(parsed.filters.customer_ids)
    entity_ids = customer_ids[:1] if customer_ids else ["UNKNOWN"]
    return ValidatedPlan(
        strategy="pattern_structuring",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="feat1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "subthreshold_count",
                    "entity_ids": cast(JsonValue, entity_ids),
                    "window_days": 30,
                    "currency": parsed.filters.currency or "USD",
                },
                reason="structuring feature support",
            ),
            PlanStep(
                step_id="anom1",
                tool=ToolName.ANOMALY_DETECTION,
                operation="detect",
                parameters={
                    "mode": "rules_only",
                    "entity_id": entity_ids[0],
                },
                reason="rules signal for structuring pattern",
                depends_on=["feat1"],
            ),
        ],
    )


def plan_entity_investigation(parsed: ParsedIntent) -> ValidatedPlan:
    customer_id = (parsed.filters.customer_ids or ["UNKNOWN"])[0]
    return ValidatedPlan(
        strategy="entity_investigation",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": customer_id},
                reason="load customer entity",
            ),
            PlanStep(
                step_id="feat1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_count",
                    "entity_ids": cast(JsonValue, [customer_id]),
                    "window_days": 30,
                },
                reason="entity activity features",
                depends_on=["sql1"],
            ),
            PlanStep(
                step_id="anom1",
                tool=ToolName.ANOMALY_DETECTION,
                operation="detect",
                parameters={"mode": "hybrid", "entity_id": customer_id},
                reason="entity anomaly signals",
                depends_on=["feat1"],
                required=False,
            ),
        ],
    )


def plan_broad_exploration() -> ValidatedPlan:
    return ValidatedPlan(
        strategy="broad_exploration",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="eda1",
                tool=ToolName.EDA,
                operation="cohort_profile",
                parameters={},
                reason="dataset cohort profiling",
            ),
            PlanStep(
                step_id="eda2",
                tool=ToolName.EDA,
                operation="volume_over_time",
                parameters={},
                reason="volume trend",
                depends_on=["eda1"],
                required=False,
            ),
        ],
    )


def plan_simple_customer_lookup(parsed: ParsedIntent) -> ValidatedPlan:
    customer_id = (parsed.filters.customer_ids or ["UNKNOWN"])[0]
    return ValidatedPlan(
        strategy="simple_customer_lookup",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": customer_id},
                reason="simple customer lookup",
            )
        ],
    )


def plan_transaction_scoring(parsed: ParsedIntent) -> ValidatedPlan:
    txn_id = (parsed.filters.transaction_ids or ["UNKNOWN"])[0]
    return ValidatedPlan(
        strategy="transaction_scoring",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_transaction",
                parameters={"transaction_id": txn_id},
                reason="load transaction before score",
            ),
            PlanStep(
                step_id="anom1",
                tool=ToolName.ANOMALY_DETECTION,
                operation="detect",
                parameters={"mode": "ml_only", "transaction_id": txn_id},
                reason="ml score signal",
                depends_on=["sql1"],
                required=False,
            ),
        ],
    )


def default_amount_filter() -> Decimal:
    return Decimal("10000")
