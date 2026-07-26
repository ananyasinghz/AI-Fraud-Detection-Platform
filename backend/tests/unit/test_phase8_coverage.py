"""Extra coverage for Phase 8 aggregator / explanation generator paths."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.app.core.config import Settings
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import EvidenceReference, ToolProvenance, ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.evidence.aggregator import (
    collect_evidence_refs,
    extract_anomaly_signals,
    extract_graph_findings,
    required_tool_results_present,
)
from backend.app.explanation.generator import _extract_json, generate_explanation

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)


def _tr(
    tool: ToolName,
    operation: str,
    data: dict[str, Any],
    *,
    status: ToolStatus = ToolStatus.SUCCESS,
    evidence: list[EvidenceReference] | None = None,
    warnings: list[str] | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        operation=operation,
        status=status,
        produced_at=AS_OF,
        scope=NormalizedFilters(),
        data=data,
        duration_ms=1,
        evidence=evidence if evidence is not None else [],
        warnings=warnings or (["SKIPPED"] if status is ToolStatus.SKIPPED else []),
        provenance=ToolProvenance(source=tool.value, query_or_version="t"),
    )


def test_aggregator_synthetic_refs_and_graph_extract() -> None:
    results = [
        _tr(ToolName.SQL_LOOKUP, "get_customer", {"id": "C1"}),
        _tr(
            ToolName.ANOMALY_DETECTION,
            "detect",
            {"rules": []},
            evidence=[
                EvidenceReference(
                    evidence_id="anom.1",
                    tool=ToolName.ANOMALY_DETECTION,
                    kind="tool_result",
                    json_path="$.data",
                    label="anom",
                )
            ],
        ),
        _tr(
            ToolName.GRAPH_ANALYSIS,
            "circular_transfers",
            {"cycles": [["a", "b"]], "findings": [{"customer_ids": ["C1", "C2"]}]},
        ),
        _tr(ToolName.GRAPH_ANALYSIS, "two_hop_exposure", {"count": 2}),
        _tr(
            ToolName.GRAPH_ANALYSIS,
            "shared_device",
            {"count": 0},
            status=ToolStatus.SKIPPED,
        ),
    ]
    refs = collect_evidence_refs(results)
    assert any(item.evidence_id == "anom.1" for item in refs)
    assert any(item.evidence_id.startswith("sql_lookup.") for item in refs)
    assert extract_anomaly_signals(results) == {"rules": []}
    findings = extract_graph_findings(results)
    assert any("cycles" in item for item in findings)
    assert any(item.get("operation") == "two_hop_exposure" for item in findings)
    ok, missing = required_tool_results_present(
        results, required_tools={ToolName.SQL_LOOKUP, ToolName.EDA}
    )
    assert not ok
    assert "eda" in missing


def test_explanation_json_extract_and_ollama_success_path() -> None:
    assert _extract_json('{"a": 1}')["a"] == 1
    assert _extract_json('noise {"b": 2} trailing')["b"] == 2

    payload = {
        "entity_id": "C1",
        "risk_score": 40.0,
        "risk_level": "MEDIUM",
        "confidence": 0.7,
        "reasons": ["ok"],
        "evidence_ids": ["ev-1"],
        "escalation_action": "review",
        "contributing_signals": [{"type": "rule", "rule_id": "R1"}],
        "warnings": ["INSUFFICIENT"],
    }
    disabled = generate_explanation(
        payload,
        settings=Settings(environment="test", explanation_enabled=False),
    )
    assert disabled["source"] == "disabled_template"
    assert (
        "Uncertainty" in disabled["uncertainty_note"]
        or "INSUFFICIENT" in disabled["uncertainty_note"]
    )

    def good(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": {
                "content": (
                    '{"summary":"ok 40","reasons":["ok"],'
                    '"risk_level_explanation":"MEDIUM",'
                    '"recommended_action_explanation":"review",'
                    '"uncertainty_note":"none","evidence_ids":["ev-1"],'
                    '"claims":[{"claim":"ok","evidence_ids":["ev-1"]}]}'
                )
            }
        }

    ok = generate_explanation(
        payload,
        settings=Settings(environment="test", ollama_enabled=True, explanation_enabled=True),
        transport=good,
    )
    assert ok["source"] == "ollama"

    def bad_shape(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {"message": {"content": 123}}

    fallback = generate_explanation(
        payload,
        settings=Settings(environment="test", ollama_enabled=True, explanation_enabled=True),
        transport=bad_shape,
    )
    assert fallback["source"] == "template_fallback"


def test_classifier_graph_and_insufficient_paths() -> None:
    from pathlib import Path

    from backend.app.risk.classifier import classify_transaction_risk
    from backend.app.risk.policy import load_risk_policy

    policy = load_risk_policy(Path("config/policy/risk_scoring.v1.yaml"))
    result = classify_transaction_risk(
        entity_id="T9",
        anomaly_payload={"ml": {"ml_score": "bad"}, "statistics": {"mad": 3}},
        graph_findings=[
            {"operation": "shared_device", "customer_ids": ["a", "b"]},
            {"operation": "two_hop_exposure", "count": 1},
            {"operation": "other"},
        ],
        policy=policy,
        evidence_ids=["e"],
        confidence_cap=0.4,
        insufficient_data=True,
    )
    assert result.risk_score >= 0
    assert result.confidence <= 0.4
    assert "INSUFFICIENT_DATA_PENALTY" in result.warnings
