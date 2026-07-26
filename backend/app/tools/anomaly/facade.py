"""Anomaly facade: rules, statistics, ML signals (no final risk tier)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.app.data.query_scope import QueryScope
from backend.app.data.repositories import TransactionRepository
from backend.app.domain.enums import EntityType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.rules import RULE_ENGINE, RuleInput
from backend.app.services.feature_ref import features_as_mapping, load_ulb_features
from backend.app.tools.anomaly.rule_bundles import (
    RULE_FEATURE_OPS,
    build_rule_feature_requests,
)
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

    requested = parameters.get("rule_ids")
    if requested is None:
        rule_ids = tuple(rid for rid in RULE_ENGINE.registered() if rid in RULE_FEATURE_OPS)
    else:
        if not isinstance(requested, (list, tuple)):
            return [], ["rule_ids must be a list of rule id strings"]
        rule_ids = tuple(str(item) for item in requested)
        unknown = [rid for rid in rule_ids if rid not in RULE_FEATURE_OPS]
        if unknown:
            return [], [f"unknown rule_ids: {', '.join(unknown)}"]

    warnings: list[str] = []
    rule_inputs: dict[str, RuleInput] = {}
    for rule_id in rule_ids:
        try:
            requests = build_rule_feature_requests(
                rule_id=rule_id,
                entity_id=entity_id,
                as_of=context.as_of,
                policy=context.policy,
            )
            features = []
            for request in requests:
                scope = QueryScope.from_feature_request(context.filters, request)
                feature = FEATURE_REGISTRY(
                    session=context.session,
                    policy=context.policy,
                    request=request,
                    scope=scope,
                )
                warnings.extend(warning.message for warning in feature.warnings)
                features.append(feature)
            rule_inputs[rule_id] = RuleInput(
                entity_type=EntityType.CUSTOMER,
                entity_id=entity_id,
                feature_results=tuple(features),
            )
        except Exception as exc:
            warnings.append(f"rule_features_failed:{rule_id}:{exc}")

    if not rule_inputs:
        return [], warnings or ["no rules could be evaluated"]

    results = RULE_ENGINE.evaluate_many(
        rule_inputs=rule_inputs,
        policy=context.policy,
    )
    return [item.model_dump(mode="json") for item in results], warnings


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
