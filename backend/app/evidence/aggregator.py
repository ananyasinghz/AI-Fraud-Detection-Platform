"""Collect evidence references and signal summaries from prior tool results."""

from __future__ import annotations

from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import EvidenceReference, ToolResult


def collect_evidence_refs(results: list[ToolResult]) -> list[EvidenceReference]:
    refs: list[EvidenceReference] = []
    seen: set[str] = set()
    for result in results:
        for item in result.evidence:
            if item.evidence_id in seen:
                continue
            seen.add(item.evidence_id)
            refs.append(item)
        # Synthesize refs when tools omit explicit evidence lists.
        if not result.evidence and result.status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}:
            synthetic_id = f"{result.tool.value}.{result.operation}.{len(seen)}"
            if synthetic_id not in seen:
                seen.add(synthetic_id)
                refs.append(
                    EvidenceReference(
                        evidence_id=synthetic_id,
                        tool=result.tool,
                        kind="tool_result",
                        json_path="$.data",
                        label=f"{result.tool.value}:{result.operation}",
                    )
                )
    return refs


def extract_anomaly_signals(results: list[ToolResult]) -> dict[str, Any]:
    """Return the latest successful anomaly_detection payload."""
    for result in reversed(results):
        if result.tool is ToolName.ANOMALY_DETECTION and result.status in {
            ToolStatus.SUCCESS,
            ToolStatus.PARTIAL,
        }:
            return dict(result.data)
    return {}


def extract_graph_findings(results: list[ToolResult]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for result in results:
        if result.tool is not ToolName.GRAPH_ANALYSIS:
            continue
        if result.status not in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}:
            continue
        payload = result.data
        findings_raw = payload.get("findings")
        if isinstance(findings_raw, list):
            for item in findings_raw:
                if isinstance(item, dict):
                    findings.append({"operation": result.operation, **dict(item)})
        cycles_raw = payload.get("cycles")
        if isinstance(cycles_raw, list) and cycles_raw:
            findings.append({"operation": result.operation, "cycles": cycles_raw})
        if result.operation == "two_hop_exposure":
            count_raw = payload.get("count")
            count = 0
            if isinstance(count_raw, (int, float, str)):
                try:
                    count = int(count_raw)
                except (TypeError, ValueError):
                    count = 0
            if count > 0:
                findings.append({"operation": result.operation, "count": count})
    return findings


def required_tool_results_present(
    results: list[ToolResult],
    *,
    required_tools: set[ToolName],
) -> tuple[bool, list[str]]:
    present = {
        result.tool
        for result in results
        if result.status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}
    }
    missing = sorted(tool.value for tool in required_tools - present)
    return (not missing, missing)
