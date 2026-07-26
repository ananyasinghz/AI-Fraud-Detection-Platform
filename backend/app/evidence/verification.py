"""Stage 1 evidence verification before risk classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.evidence.aggregator import collect_evidence_refs


@dataclass
class EvidenceVerificationResult:
    ok: bool
    block_risk: bool
    warnings: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    confidence_cap: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def verify_evidence(
    results: list[ToolResult],
    *,
    requested_scope: NormalizedFilters,
    require_anomaly_or_feature: bool = False,
) -> EvidenceVerificationResult:
    """Validate prior tool outputs before risk runs."""
    warnings: list[str] = []
    block = False
    details: dict[str, Any] = {}

    if not results:
        return EvidenceVerificationResult(
            ok=False,
            block_risk=True,
            warnings=["NO_PRIOR_TOOL_RESULTS"],
            details={"reason": "no tool results to verify"},
        )

    refs = collect_evidence_refs(results)
    evidence_ids = [item.evidence_id for item in refs]
    if not evidence_ids:
        warnings.append("NO_EVIDENCE_REFS")
        block = True

    # Scope mismatch: successful tool scopes must not silently widen beyond request.
    for result in results:
        if result.status not in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}:
            continue
        if _scope_widened(requested_scope, result.scope):
            warnings.append(f"SCOPE_MISMATCH:{result.tool.value}")
            block = True

    # Provenance / version presence for successful analytical tools.
    for result in results:
        if result.status not in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}:
            continue
        if result.tool in {
            ToolName.FEATURE_ENGINEERING,
            ToolName.ANOMALY_DETECTION,
            ToolName.EDA,
        }:
            if not result.provenance.query_or_version:
                warnings.append(f"MISSING_VERSION:{result.tool.value}")
                block = True
            if (
                result.provenance.policy_version is None
                and result.tool is ToolName.ANOMALY_DETECTION
            ):
                warnings.append("MISSING_POLICY_VERSION:anomaly_detection")

        # Hidden labels / LLM claim markers are forbidden in runtime payloads.
        blob = str(result.data)
        for banned in ("scenario_label", "is_suspicious", "held_out_label", "llm_claim"):
            if banned in blob:
                warnings.append(f"FORBIDDEN_FIELD:{banned}")
                block = True

        # Structural completeness for anomaly results (data is always a mapping).
        if result.tool is ToolName.ANOMALY_DETECTION and not result.data:
            warnings.append("INVALID_ANOMALY_STRUCTURE")
            block = True

        if any(
            "INSUFFICIENT" in w or "NO_DATA" in w or "missing" in w.lower() for w in result.warnings
        ):
            warnings.append(f"DATA_SUFFICIENCY:{result.tool.value}")

    confidence_cap: float | None = None
    if any(w.startswith("DATA_SUFFICIENCY") for w in warnings):
        confidence_cap = 0.55
        details["insufficient_data"] = True

    if require_anomaly_or_feature:
        has_signal = any(
            result.tool in {ToolName.ANOMALY_DETECTION, ToolName.FEATURE_ENGINEERING}
            and result.status in {ToolStatus.SUCCESS, ToolStatus.PARTIAL}
            for result in results
        )
        if not has_signal:
            warnings.append("MISSING_REQUIRED_SIGNAL_TOOLS")
            block = True

    ok = not block
    return EvidenceVerificationResult(
        ok=ok,
        block_risk=block,
        warnings=warnings,
        evidence_ids=evidence_ids,
        confidence_cap=confidence_cap,
        details=details,
    )


def _scope_widened(requested: NormalizedFilters, actual: NormalizedFilters) -> bool:
    """True when actual scope is broader than requested on entity ID axes."""
    if (
        requested.customer_ids
        and actual.customer_ids
        and not set(actual.customer_ids).issubset(set(requested.customer_ids))
    ):
        return True
    if (
        requested.account_ids
        and actual.account_ids
        and not set(actual.account_ids).issubset(set(requested.account_ids))
    ):
        return True
    return bool(
        requested.transaction_ids
        and actual.transaction_ids
        and not set(actual.transaction_ids).issubset(set(requested.transaction_ids))
    )
