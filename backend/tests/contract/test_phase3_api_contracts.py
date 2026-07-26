"""Contract tests for Phase 3 API and chart models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.domain.api import (
    AlertCreateRequest,
    AlertPatchRequest,
    QueryRequest,
    ScoreResponse,
)
from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import ChartType, EntityType, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan


def test_query_and_alert_contracts_validate() -> None:
    as_of = datetime(2026, 2, 1, tzinfo=UTC)
    plan = ValidatedPlan(
        strategy="lookup",
        planner_version="contract.v1",
        steps=[
            PlanStep(
                step_id="s1",
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                parameters={"customer_id": "C1"},
                reason="lookup",
            )
        ],
    )
    query = QueryRequest(query="lookup C1", as_of=as_of, plan=plan)
    assert query.filters == NormalizedFilters()

    alert = AlertCreateRequest(
        entity_type=EntityType.CUSTOMER,
        entity_id="C1",
        finding_code="STRUCTURING_SIGNAL",
        severity="high",
        evidence_snapshot_ref="ev.alert.1",
        policy_version="reporting_thresholds.v1",
        investigation_window_start=as_of,
        investigation_window_end=datetime(2026, 2, 8, tzinfo=UTC),
        request_id="req-1",
    )
    assert alert.severity == "high"

    with pytest.raises(ValidationError):
        AlertPatchRequest(
            status="open",
            reviewer_id="rev-1",
            reason="",
            request_id="req-2",
        )


def test_chart_spec_and_score_response_contracts() -> None:
    chart = ChartSpec(
        chart_id="volume-over-time",
        chart_type=ChartType.LINE,
        title="Volume",
        data={"labels": ["2026-01-01"], "values": [3]},
        evidence_refs=["ev.1"],
    )
    assert chart.chart_type is ChartType.LINE
    skipped = ScoreResponse(transaction_id="T1", status="skipped", reason="ML_INELIGIBLE")
    assert skipped.ml_score is None
