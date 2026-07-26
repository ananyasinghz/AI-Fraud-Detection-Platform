"""Feature-engineering tool wrapping the Phase 2 FeatureRegistry."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from backend.app.data.query_scope import QueryScope
from backend.app.domain.enums import EntityType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolError, ToolProvenance, ToolResult
from backend.app.domain.features import (
    EntityScope,
    FeatureRequest,
    FeatureWindow,
    TransactionFilter,
)
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result
from backend.app.tools.features.registry import FEATURE_REGISTRY, UnknownFeatureOperationError


def handle_feature_engineering(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> ToolResult:
    timer = Timer()
    provenance = ToolProvenance(
        source="feature_engineering",
        query_or_version="feature_engineering.v1",
        policy_version=context.policy.version,
    )
    if operation not in {"compute_feature", "run_operation"}:
        raise ValueError(f"unknown feature_engineering operation: {operation}")

    feature_operation = str(parameters.get("feature_operation") or parameters.get("operation", ""))
    version = str(parameters.get("version", "v1"))
    entity_type = EntityType(str(parameters.get("entity_type", "customer")))
    entity_ids = parameters.get("entity_ids")
    if not isinstance(entity_ids, list) or not entity_ids:
        raise ValueError("entity_ids must be a non-empty list")
    window_days = int(parameters.get("window_days", 30))
    currency = parameters.get("currency")
    request = FeatureRequest(
        operation=feature_operation,
        version=version,
        as_of=context.as_of,
        window=FeatureWindow(
            start_inclusive=context.as_of - timedelta(days=window_days),
            end_exclusive=context.as_of,
        ),
        scope=EntityScope(
            entity_type=entity_type,
            entity_ids=tuple(str(item) for item in entity_ids),
        ),
        transaction_filter=TransactionFilter(
            currency=str(currency) if currency is not None else None,
        ),
    )
    scope = QueryScope.from_feature_request(context.filters, request)
    try:
        result = FEATURE_REGISTRY(
            session=context.session,
            policy=context.policy,
            request=request,
            scope=scope,
        )
    except UnknownFeatureOperationError as exc:
        return make_result(
            tool=ToolName.FEATURE_ENGINEERING,
            operation=operation,
            status=ToolStatus.FAILED,
            scope=context.filters,
            duration_ms=timer.ms(),
            provenance=provenance,
            error=ToolError(code="UNKNOWN_FEATURE", message=str(exc), retryable=False),
        )

    return make_result(
        tool=ToolName.FEATURE_ENGINEERING,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={"feature_result": result.model_dump(mode="json")},
        warnings=[item.message for item in result.warnings],
        duration_ms=timer.ms(),
        provenance=ToolProvenance(
            source=result.provenance.source,
            query_or_version=result.provenance.query_id or "feature_engineering.v1",
            dataset_version=result.provenance.dataset_version,
            policy_version=result.provenance.policy_version,
        ),
    )
