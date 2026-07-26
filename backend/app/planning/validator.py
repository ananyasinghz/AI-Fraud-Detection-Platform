"""Semantic plan validator beyond ValidatedPlan graph checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from backend.app.domain.enums import IntentType, TargetScope, ToolName
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.planning.schemas import ALLOWED_OPERATIONS, BLOCKED_TOOLS, PLANNER_WHITELIST


@dataclass(frozen=True)
class ValidationResult:
    plan: ValidatedPlan | None
    reasons: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.plan is not None and not self.reasons


def _reject(*reasons: str) -> ValidationResult:
    return ValidationResult(plan=None, reasons=tuple(reasons))


def validate_plan_semantics(
    draft: dict[str, Any] | ValidatedPlan,
    *,
    parsed: ParsedIntent,
    planner_version: str,
    max_steps: int = 20,
) -> ValidationResult:
    """Validate whitelist, scope compatibility, and domain graph constraints."""
    if isinstance(draft, ValidatedPlan):
        candidate = draft
    else:
        try:
            payload = dict(draft)
            payload.setdefault("planner_version", planner_version)
            payload.setdefault("strategy", payload.get("strategy") or "dynamic_plan")
            if "steps" not in payload or not isinstance(payload["steps"], list):
                return _reject("missing_or_invalid_steps")
            if len(payload["steps"]) > max_steps:
                return _reject(f"too_many_steps:{len(payload['steps'])}")
            if len(payload["steps"]) < 1:
                return _reject("empty_plan")
            candidate = ValidatedPlan.model_validate(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            return _reject(f"schema_invalid:{exc}")

    if len(candidate.steps) > max_steps:
        return _reject(f"too_many_steps:{len(candidate.steps)}")

    reasons: list[str] = []
    tools_used: set[ToolName] = set()
    for step in candidate.steps:
        tools_used.add(step.tool)
        if step.tool in BLOCKED_TOOLS or step.tool not in PLANNER_WHITELIST:
            reasons.append(f"tool_not_whitelisted:{step.tool.value}")
            continue
        allowed = ALLOWED_OPERATIONS.get(step.tool, frozenset())
        if step.operation not in allowed:
            reasons.append(f"unknown_operation:{step.tool.value}.{step.operation}")

        if step.tool is ToolName.SQL_LOOKUP and step.operation == "get_customer":
            customer_id = step.parameters.get("customer_id")
            if not customer_id and not parsed.filters.customer_ids:
                reasons.append("missing_customer_id_for_sql")
        if step.tool is ToolName.SQL_LOOKUP and step.operation == "get_transaction":
            txn_id = step.parameters.get("transaction_id")
            if not txn_id and not parsed.filters.transaction_ids:
                reasons.append("missing_transaction_id_for_sql")
        if step.tool is ToolName.FEATURE_ENGINEERING:
            entity_ids = step.parameters.get("entity_ids")
            if (
                not isinstance(entity_ids, list) or not entity_ids
            ) and not parsed.filters.customer_ids:
                reasons.append("missing_entity_ids_for_feature")
        if step.tool is ToolName.ANOMALY_DETECTION:
            mode = step.parameters.get("mode")
            if mode not in {None, "rules_only", "ml_only", "hybrid"}:
                reasons.append(f"invalid_anomaly_mode:{mode}")

    # Over-broad EDA on entity-scoped investigations.
    entity_scoped = (
        parsed.target_scope in {TargetScope.CUSTOMER, TargetScope.ACCOUNT, TargetScope.TRANSACTION}
        or bool(parsed.filters.customer_ids)
        or bool(parsed.filters.transaction_ids)
    )
    entity_intents = {
        IntentType.ENTITY_INVESTIGATION,
        IntentType.SIMPLE_LOOKUP,
        IntentType.FEATURE_COMPARISON,
        IntentType.TRANSACTION_SCORING,
        IntentType.PATTERN_SEARCH,
    }
    if entity_scoped and ToolName.EDA in tools_used and parsed.intent in entity_intents:
        reasons.append("over_broad_eda_on_entity_scope")

    # SQL-only / feature-only intents must not invent risk-style breadth.
    if parsed.intent is IntentType.SIMPLE_LOOKUP and ToolName.EDA in tools_used:
        reasons.append("eda_not_allowed_for_simple_lookup")
    if parsed.intent is IntentType.SIMPLE_LOOKUP and ToolName.ANOMALY_DETECTION in tools_used:
        reasons.append("anomaly_not_allowed_for_simple_lookup")
    if parsed.intent is IntentType.FEATURE_COMPARISON and ToolName.EDA in tools_used:
        reasons.append("eda_not_allowed_for_feature_comparison")

    if reasons:
        return _reject(*reasons)
    return ValidationResult(plan=candidate, reasons=())


def steps_from_raw(raw_steps: list[dict[str, Any]]) -> list[PlanStep]:
    return [PlanStep.model_validate(item) for item in raw_steps]
