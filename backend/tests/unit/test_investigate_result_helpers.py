"""Unit coverage for Investigate result correctness helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolProvenance, ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.workflow.nodes.aggregate import _spend_comparison_payload


def _feature_total(role: str, minor: int, customer_id: str = "C1") -> ToolResult:
    return ToolResult(
        tool=ToolName.FEATURE_ENGINEERING,
        operation="compute_feature",
        status=ToolStatus.SUCCESS,
        scope=NormalizedFilters(customer_ids=[customer_id]),
        data={
            "window_role": role,
            "feature_result": {
                "values": [
                    {
                        "name": "transaction_total",
                        "value_type": "decimal",
                        "value": str(Decimal(minor)),
                        "unit": "USD_minor",
                    }
                ]
            },
        },
        duration_ms=1,
        produced_at=datetime(2026, 7, 25, tzinfo=UTC),
        provenance=ToolProvenance(source="test", query_or_version="t"),
    )


def test_spend_comparison_payload_elevated() -> None:
    state = SimpleNamespace(
        tool_results=[
            _feature_total("current", 300_000),
            _feature_total("prior", 100_000),
        ]
    )
    payload = _spend_comparison_payload(state)  # type: ignore[arg-type]
    assert payload is not None
    summary, data = payload
    assert "Elevated vs prior baseline: yes" in summary
    assert data["spend_comparison"]["elevated"] is True
    assert data["spend_comparison"]["ratio"] == 3.0


def test_spend_comparison_payload_not_elevated() -> None:
    state = SimpleNamespace(
        tool_results=[
            _feature_total("current", 110_000),
            _feature_total("prior", 100_000),
        ]
    )
    payload = _spend_comparison_payload(state)  # type: ignore[arg-type]
    assert payload is not None
    _, data = payload
    assert data["spend_comparison"]["elevated"] is False
