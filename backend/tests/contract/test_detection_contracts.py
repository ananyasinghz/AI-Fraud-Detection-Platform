"""Focused tests for immutable feature and rule contracts."""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.app.domain import (
    EntityScope,
    EntityType,
    FeatureDenominator,
    FeatureGrouping,
    FeatureProvenance,
    FeatureRequest,
    FeatureResult,
    FeatureValue,
    FeatureWarning,
    FeatureWindow,
    RuleResult,
    RuleSeverity,
    RuleThreshold,
    TransactionDirection,
    TransactionFilter,
    ValueType,
)

AS_OF = datetime(2026, 7, 25, 12, tzinfo=UTC)


def make_request() -> FeatureRequest:
    return FeatureRequest(
        operation="round_number_ratio",
        version="round_number_ratio.v1",
        as_of=AS_OF,
        window=FeatureWindow(
            start_inclusive=AS_OF - timedelta(days=30),
            end_exclusive=AS_OF,
        ),
        scope=EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C123",)),
        transaction_filter=TransactionFilter(
            transaction_types=("wire_transfer",),
            directions=(TransactionDirection.CREDIT,),
            countries=("US",),
            currency="USD",
        ),
        group_by=(FeatureGrouping.DAY,),
    )


def test_feature_result_carries_typed_scope_quality_and_provenance() -> None:
    request = make_request()
    result = FeatureResult(
        request=request,
        values=(
            FeatureValue(
                name="round_number_ratio",
                value_type=ValueType.DECIMAL,
                value=Decimal("0.8"),
                unit="ratio",
            ),
        ),
        denominators=(
            FeatureDenominator(name="eligible_transactions", value=10, unit="transactions"),
        ),
        warnings=(FeatureWarning(code="PARTIAL_HISTORY", message="Only 30 days were available"),),
        provenance=FeatureProvenance(
            source="transaction_repository",
            dataset_version="aml.v1",
            operation_version="round_number_ratio.v1",
            policy_version="reporting_thresholds.v1",
        ),
    )

    assert result.request.window.end_exclusive == AS_OF
    assert result.values[0].value == Decimal("0.8")
    with pytest.raises(ValidationError, match="frozen"):
        result.request.operation = "changed"


def test_feature_contracts_require_strict_utc_and_half_open_windows() -> None:
    with pytest.raises(ValidationError, match="UTC-aware"):
        FeatureWindow(
            start_inclusive=datetime(2026, 7, 1),
            end_exclusive=AS_OF,
        )
    with pytest.raises(ValidationError, match="UTC-aware"):
        FeatureWindow(
            start_inclusive=AS_OF.astimezone(timezone(timedelta(hours=5, minutes=30))),
            end_exclusive=AS_OF,
        )
    with pytest.raises(ValidationError, match="start_inclusive"):
        FeatureWindow(start_inclusive=AS_OF, end_exclusive=AS_OF)
    with pytest.raises(ValidationError):
        FeatureRequest.model_validate(
            {
                **make_request().model_dump(),
                "as_of": "2026-07-25T12:00:00Z",
            }
        )


def test_feature_request_rejects_future_window_and_duplicate_scope() -> None:
    with pytest.raises(ValidationError, match="after as_of"):
        FeatureRequest(
            operation="velocity",
            version="velocity.v1",
            as_of=AS_OF,
            window=FeatureWindow(
                start_inclusive=AS_OF,
                end_exclusive=AS_OF + timedelta(hours=1),
            ),
            scope=EntityScope(entity_type=EntityType.ACCOUNT, entity_ids=("A1",)),
        )
    with pytest.raises(ValidationError, match="duplicates"):
        EntityScope(entity_type=EntityType.CUSTOMER, entity_ids=("C1", "C1"))


def test_typed_values_reject_declared_type_mismatches() -> None:
    with pytest.raises(ValidationError, match="declared value_type"):
        FeatureValue(name="count", value_type=ValueType.INTEGER, value=True)
    with pytest.raises(ValidationError, match="finite"):
        FeatureValue(name="ratio", value_type=ValueType.FLOAT, value=float("nan"))


def test_rule_result_records_all_audit_inputs() -> None:
    result = RuleResult(
        rule_id="structuring.v1",
        version="v1",
        fired=True,
        severity=RuleSeverity.HIGH,
        entity_type=EntityType.CUSTOMER,
        entity_id="C123",
        features_used=(
            FeatureValue(
                name="sub_threshold_count",
                value_type=ValueType.INTEGER,
                value=4,
                unit="transactions",
            ),
        ),
        thresholds_used=(
            RuleThreshold(
                name="minimum_count",
                value_type=ValueType.INTEGER,
                value=3,
                unit="transactions",
            ),
        ),
        evidence_refs=("ev.features.1",),
        reason_code="MULTIPLE_SUB_THRESHOLD_CASH_DEPOSITS",
    )

    assert result.fired is True
    assert result.thresholds_used[0].value == 3
    with pytest.raises(ValidationError, match="duplicates"):
        RuleResult.model_validate(
            result.model_dump()
            | {
                "evidence_refs": ("ev.features.1", "ev.features.1"),
            }
        )
