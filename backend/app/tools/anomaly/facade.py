"""Anomaly facade: rules, statistics, ML signals (no final risk tier)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import TransactionRepository
from backend.app.domain.enums import EntityType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.domain.features import (
    EntityScope,
    FeatureRequest,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.rules import RULE_ENGINE, RuleInput
from backend.app.services.feature_ref import features_as_mapping, load_ulb_features
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result
from backend.app.tools.features.registry import FEATURE_REGISTRY
from backend.app.tools.statistics import (
    IqrOutlierRequest,
    RobustZScoreRequest,
    iqr_outliers,
    robust_z_score,
)


def handle_anomaly_detection(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> ToolResult:
    timer = Timer()
    provenance = ToolProvenance(
        source="anomaly_detection",
        query_or_version="anomaly_detection.v1",
        policy_version=context.policy.version,
    )
    if operation != "detect":
        raise ValueError(f"unknown anomaly_detection operation: {operation}")

    mode = str(parameters.get("mode", "hybrid"))
    if mode not in {"rules_only", "statistical_only", "ml_only", "hybrid"}:
        raise ValueError(f"unsupported anomaly mode: {mode}")

    warnings: list[str] = []
    signals: dict[str, Any] = {"mode": mode, "rules": [], "statistics": {}, "ml": None}

    if mode in {"rules_only", "hybrid"}:
        signals["rules"], rule_warnings = _run_rules(context, parameters)
        warnings.extend(rule_warnings)

    if mode in {"statistical_only", "hybrid"}:
        signals["statistics"], stat_warnings = _run_statistics(context)
        warnings.extend(stat_warnings)

    if mode in {"ml_only", "hybrid"}:
        ml_payload, ml_warnings, skipped = _run_ml(context, parameters)
        signals["ml"] = ml_payload
        warnings.extend(ml_warnings)
        if mode == "ml_only" and skipped:
            return make_result(
                tool=ToolName.ANOMALY_DETECTION,
                operation=operation,
                status=ToolStatus.SKIPPED,
                scope=context.filters,
                data=signals,
                warnings=warnings or ["ML_INELIGIBLE"],
                duration_ms=timer.ms(),
                provenance=provenance,
            )

    status = ToolStatus.SUCCESS
    if warnings and (not signals["rules"] and signals["ml"] is None):
        status = ToolStatus.PARTIAL
    return make_result(
        tool=ToolName.ANOMALY_DETECTION,
        operation=operation,
        status=status,
        scope=context.filters,
        data=signals,
        warnings=warnings,
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _run_rules(
    context: ToolContext,
    parameters: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    entity_id = str(parameters.get("entity_id") or (context.filters.customer_ids[:1] or [""])[0])
    if not entity_id:
        return [], ["rules require entity_id or customer_ids filter"]
    window_days = int(parameters.get("window_days", context.policy.structuring.window_days))
    request = FeatureRequest(
        operation="subthreshold_count",
        version="v1",
        as_of=context.as_of,
        window=FeatureWindow(
            start_inclusive=context.as_of - timedelta(days=window_days),
            end_exclusive=context.as_of,
        ),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=(entity_id,)),
        transaction_filter=TransactionFilter(currency=context.policy.currency),
    )
    scope = QueryScope.from_feature_request(context.filters, request)
    feature = FEATURE_REGISTRY(
        session=context.session,
        policy=context.policy,
        request=request,
        scope=scope,
    )
    rule_input = RuleInput(
        entity_type=EntityType.CUSTOMER,
        entity_id=entity_id,
        feature_results=(feature,),
    )
    result = RULE_ENGINE.dispatch("structuring.v1", rule_input=rule_input, policy=context.policy)
    return [result.model_dump(mode="json")], [warning.message for warning in feature.warnings]


def _run_statistics(context: ToolContext) -> tuple[dict[str, Any], list[str]]:
    scope = QueryScope.from_filters(context.filters, as_of=context.as_of)
    rows = TransactionRepository(context.session).list_scoped(scope)
    amounts = tuple(Decimal(item.amount_minor) for item in rows)
    if not amounts:
        return {}, ["no amounts available for statistical signals"]
    current = amounts[-1]
    reference = amounts[:-1] or amounts
    z = robust_z_score(
        RobustZScoreRequest(value=current, reference_values=reference, minimum_sample_size=1)
    )
    iqr = iqr_outliers(IqrOutlierRequest(values=amounts, minimum_sample_size=1))
    return (
        {
            "robust_z_score": z.model_dump(mode="json"),
            "iqr_outliers": iqr.model_dump(mode="json"),
        },
        [item.message for item in z.warnings] + [item.message for item in iqr.warnings],
    )


def _run_ml(
    context: ToolContext,
    parameters: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str], bool]:
    transaction_id = str(parameters.get("transaction_id", ""))
    if not transaction_id:
        return None, ["ml requires transaction_id"], True
    transaction = TransactionRepository(context.session).get_by_id(transaction_id)
    if transaction is None:
        return None, [f"transaction not found: {transaction_id}"], True
    if not transaction.ml_eligible or not transaction.ml_feature_ref:
        return (
            {
                "transaction_id": transaction_id,
                "skipped": True,
                "reason": "ML_INELIGIBLE",
            },
            ["ML_INELIGIBLE"],
            True,
        )

    scorer = context.get_scorer()
    if scorer is None:
        return (
            {
                "transaction_id": transaction_id,
                "skipped": True,
                "reason": "SCORER_UNAVAILABLE",
            },
            ["SCORER_UNAVAILABLE"],
            True,
        )

    try:
        features = load_ulb_features(transaction.ml_feature_ref)
        # Lazy import keeps backend.app.ml out of app import graph.
        from backend.app.ml.fraud_scorer import FraudScorer

        ordered = FraudScorer.validate_ordered_mapping(features_as_mapping(features))
        score = scorer.score_one(ordered)
    except Exception as exc:
        return (
            {
                "transaction_id": transaction_id,
                "skipped": True,
                "reason": "FEATURES_UNAVAILABLE",
                "detail": str(exc),
            },
            ["FEATURES_UNAVAILABLE"],
            True,
        )

    payload = {
        "transaction_id": transaction_id,
        "skipped": False,
        "ml_score": score.ml_score,
        "is_flagged": score.is_flagged,
        "threshold": score.threshold,
        "model_version": score.model_version,
        "score_semantics": score.score_semantics,
    }
    return payload, [], False
