"""Deterministic ValidatedPlan templates owned by the Phase 5 router."""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from pydantic import JsonValue

from backend.app.domain.enums import ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.nlu.pattern_plans import spec_for_pattern


def _phase8_suspicious_chain(
    *,
    depends_on: list[str],
    entity_id: str,
    classify_op: str = "classify_customer",
    required: bool = False,
) -> list[PlanStep]:
    """Evidence → risk → consistency → escalation → explanation (suspicious paths)."""
    return [
        PlanStep(
            step_id="verify1",
            tool=ToolName.VERIFICATION,
            operation="verify_evidence",
            parameters={},
            reason="stage-1 evidence verification before risk",
            depends_on=depends_on,
            required=required,
        ),
        PlanStep(
            step_id="risk1",
            tool=ToolName.RISK_CLASSIFICATION,
            operation=classify_op,
            parameters={"entity_id": entity_id},
            reason="points-model risk classification",
            depends_on=["verify1"],
            required=required,
        ),
        PlanStep(
            step_id="consist1",
            tool=ToolName.VERIFICATION,
            operation="verify_risk_consistency",
            parameters={},
            reason="stage-2 risk consistency gate",
            depends_on=["risk1"],
            required=required,
        ),
        PlanStep(
            step_id="esc1",
            tool=ToolName.ESCALATION,
            operation="recommend",
            parameters={},
            reason="deterministic escalation mapping",
            depends_on=["consist1"],
            required=required,
        ),
        PlanStep(
            step_id="expl1",
            tool=ToolName.EXPLANATION,
            operation="explain",
            parameters={},
            reason="grounded explanation of verified risk",
            depends_on=["esc1"],
            required=required,
        ),
    ]


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
    del filters  # amount_max / currency live on execution filters, not step params.
    return ValidatedPlan(
        strategy="threshold_aggregation",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="sql1",
                tool=ToolName.SQL_LOOKUP,
                operation="count_by_customer",
                parameters={"minimum_count": 10},
                reason="cohort customers with 10+ transactions under amount_max",
            ),
        ],
    )


def plan_feature_only(parsed: ParsedIntent) -> ValidatedPlan:
    customer_ids = list(parsed.filters.customer_ids) or ["UNKNOWN"]
    currency = parsed.filters.currency or "USD"
    entity_ids = cast(JsonValue, customer_ids[:1])
    return ValidatedPlan(
        strategy="feature_only",
        planner_version="router_templates.v1",
        steps=[
            PlanStep(
                step_id="feat_current",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_total",
                    "entity_ids": entity_ids,
                    "window_days": 30,
                    "window_end_offset_days": 0,
                    "window_role": "current",
                    "currency": currency,
                },
                reason="current 30d spending total",
            ),
            PlanStep(
                step_id="feat_prior",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "transaction_total",
                    "entity_ids": entity_ids,
                    "window_days": 30,
                    "window_end_offset_days": 30,
                    "window_role": "prior",
                    "currency": currency,
                },
                reason="prior 30d spending total for comparison",
                depends_on=["feat_current"],
            ),
        ],
    )


def plan_pattern_search(parsed: ParsedIntent) -> ValidatedPlan:
    """Typology-aware pattern plan; requires a customer id (router clarifies otherwise)."""
    customer_ids = list(parsed.filters.customer_ids)
    if not customer_ids:
        raise ValueError("pattern_search requires a customer id")
    entity_id = customer_ids[0]
    entity_ids = cast(JsonValue, [entity_id])
    currency = parsed.filters.currency or "USD"
    spec = spec_for_pattern(parsed.filters.pattern_type)

    steps: list[PlanStep] = []
    prior_step: str | None = None
    for index, feature_op in enumerate(spec.feature_operations, start=1):
        step_id = f"feat{index}"
        steps.append(
            PlanStep(
                step_id=step_id,
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": feature_op,
                    "entity_ids": entity_ids,
                    "window_days": spec.window_days,
                    "currency": currency,
                },
                reason=spec.reason
                if index == 1
                else f"additional {feature_op} for {spec.pattern.value}",
                depends_on=[prior_step] if prior_step else [],
            )
        )
        prior_step = step_id

    anomaly_params: dict[str, JsonValue] = {
        "mode": "rules_only",
        "entity_id": entity_id,
    }
    if spec.rule_ids is not None:
        anomaly_params["rule_ids"] = list(spec.rule_ids)

    assert prior_step is not None
    steps.append(
        PlanStep(
            step_id="anom1",
            tool=ToolName.ANOMALY_DETECTION,
            operation="detect",
            parameters=anomaly_params,
            reason=(
                f"targeted {spec.pattern.value} rule evaluation"
                if spec.rule_ids
                else "multi-rule anomaly evaluation"
            ),
            depends_on=[prior_step],
        )
    )
    steps.extend(
        _phase8_suspicious_chain(
            depends_on=["anom1"],
            entity_id=entity_id,
            classify_op="classify_customer",
            required=False,
        )
    )
    return ValidatedPlan(
        strategy=spec.strategy,
        planner_version="router_templates.v1",
        steps=steps,
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
            PlanStep(
                step_id="graph1",
                tool=ToolName.GRAPH_ANALYSIS,
                operation="shared_device",
                parameters={"customer_id": customer_id},
                reason="optional shared-device relationship check",
                depends_on=["sql1"],
                required=False,
            ),
            PlanStep(
                step_id="retr1",
                tool=ToolName.RETRIEVAL,
                operation="search_policy",
                parameters={"query": "customer investigation due diligence"},
                reason="optional policy context for reviewers",
                depends_on=["sql1"],
                required=False,
            ),
            *_phase8_suspicious_chain(
                depends_on=["anom1"],
                entity_id=customer_id,
                classify_op="classify_customer",
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
            PlanStep(
                step_id="retr1",
                tool=ToolName.RETRIEVAL,
                operation="search_policy",
                parameters={"query": "suspicious activity reporting thresholds"},
                reason="optional policy context for broad exploration",
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
            *_phase8_suspicious_chain(
                depends_on=["anom1"],
                entity_id=txn_id,
                classify_op="classify",
                required=False,
            ),
        ],
    )


def plan_explanation_request(parsed: ParsedIntent) -> ValidatedPlan:
    """Explanation with entity scope routes through investigation + grounded explain."""
    if parsed.filters.customer_ids:
        return plan_entity_investigation(parsed).model_copy(
            update={"strategy": "explanation_entity"}
        )
    if parsed.filters.transaction_ids:
        return plan_transaction_scoring(parsed).model_copy(
            update={"strategy": "explanation_transaction"}
        )
    raise ValueError("explanation requires customer or transaction scope")


def default_amount_filter() -> Decimal:
    return Decimal("10000")
