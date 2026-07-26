"""Thin tool facades for Phase 8 verification / risk / escalation / explanation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from backend.app.domain.api import AlertCreateRequest
from backend.app.domain.enums import EntityType, ToolName, ToolStatus
from backend.app.domain.evidence import ToolError, ToolProvenance
from backend.app.evidence.aggregator import (
    collect_evidence_refs,
    extract_anomaly_signals,
    extract_graph_findings,
)
from backend.app.evidence.verification import verify_evidence
from backend.app.explanation.generator import generate_explanation
from backend.app.risk.classifier import classify_transaction_risk
from backend.app.risk.consistency import verify_risk_consistency
from backend.app.risk.customer_rollup import rollup_customer_risk
from backend.app.risk.escalation import recommend_escalation
from backend.app.risk.policy import RiskScoringPolicy, get_risk_policy
from backend.app.services import alerts as alert_service
from backend.app.tools.context import ToolContext
from backend.app.tools.envelope import Timer, make_result


def _policy(context: ToolContext) -> RiskScoringPolicy:
    return get_risk_policy(str(context.settings.risk_policy_path))


def handle_verification(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    provenance = ToolProvenance(
        source="verification",
        query_or_version="verification.v1",
        policy_version=context.policy.version,
    )
    if not context.settings.risk_enabled:
        return make_result(
            tool=ToolName.VERIFICATION,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["RISK_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    if operation == "verify_evidence":
        result = verify_evidence(
            context.prior_results,
            requested_scope=context.filters,
            require_anomaly_or_feature=bool(parameters.get("require_signals", False)),
        )
        status = ToolStatus.FAILED if result.block_risk else ToolStatus.SUCCESS
        return make_result(
            tool=ToolName.VERIFICATION,
            operation=operation,
            status=status,
            scope=context.filters,
            data={
                "ok": result.ok,
                "block_risk": result.block_risk,
                "evidence_ids": result.evidence_ids,
                "confidence_cap": result.confidence_cap,
                "details": result.details,
            },
            warnings=result.warnings,
            duration_ms=timer.ms(),
            provenance=provenance,
            error=(
                None
                if status is not ToolStatus.FAILED
                else ToolError(
                    code="EVIDENCE_VERIFICATION_FAILED",
                    message="Required evidence verification failed",
                    retryable=False,
                )
            ),
        )

    if operation == "verify_risk_consistency":
        risk = _latest_risk_payload(context.prior_results)
        if risk is None:
            return make_result(
                tool=ToolName.VERIFICATION,
                operation=operation,
                status=ToolStatus.FAILED,
                scope=context.filters,
                duration_ms=timer.ms(),
                provenance=provenance,
                error=ToolError(
                    code="MISSING_RISK_RESULT",
                    message="No prior risk_classification result",
                    retryable=False,
                ),
            )
        policy = _policy(context)
        from backend.app.domain.enums import RiskLevel

        checked = verify_risk_consistency(
            risk_score=float(risk["risk_score"]),
            risk_level=RiskLevel(str(risk["risk_level"])),
            confidence=float(risk.get("confidence") or 0.5),
            contributing_signals=list(risk.get("contributing_signals") or []),
            policy=policy,
            context_only=bool(risk.get("context_only")),
            insufficient_data=bool(risk.get("insufficient_data")),
            ml_score=(float(risk["ml_score"]) if risk.get("ml_score") is not None else None),
        )
        status = ToolStatus.SUCCESS if checked.ok else ToolStatus.FAILED
        return make_result(
            tool=ToolName.VERIFICATION,
            operation=operation,
            status=status,
            scope=context.filters,
            data={
                "ok": checked.ok,
                "action": checked.action,
                "risk_score": checked.risk_score,
                "risk_level": checked.risk_level.value,
                "confidence": checked.confidence,
                "details": checked.details,
                "entity_id": risk.get("entity_id"),
                "entity_type": risk.get("entity_type"),
                "reasons": risk.get("reasons") or [],
                "evidence_ids": risk.get("evidence_ids") or [],
                "contributing_signals": risk.get("contributing_signals") or [],
                "ml_score": risk.get("ml_score"),
                "policy_version": policy.version,
            },
            warnings=checked.warnings,
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    raise ValueError(f"unknown verification operation: {operation}")


def handle_risk_classification(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    provenance = ToolProvenance(
        source="risk_classification",
        query_or_version="risk_classification.v1",
        policy_version=_policy(context).version,
    )
    if not context.settings.risk_enabled:
        return make_result(
            tool=ToolName.RISK_CLASSIFICATION,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["RISK_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    # Block if prior evidence verification failed.
    for prior in context.prior_results:
        if (
            prior.tool is ToolName.VERIFICATION
            and prior.operation == "verify_evidence"
            and prior.status is ToolStatus.FAILED
        ):
            return make_result(
                tool=ToolName.RISK_CLASSIFICATION,
                operation=operation,
                status=ToolStatus.SKIPPED,
                scope=context.filters,
                warnings=["BLOCKED_BY_EVIDENCE_VERIFICATION"],
                duration_ms=timer.ms(),
                provenance=provenance,
            )

    policy = _policy(context)
    refs = collect_evidence_refs(context.prior_results)
    evidence_ids = [item.evidence_id for item in refs]
    anomaly = extract_anomaly_signals(context.prior_results)
    graph = extract_graph_findings(context.prior_results)
    insufficient = any(
        "DATA_SUFFICIENCY" in w or "INSUFFICIENT" in w
        for result in context.prior_results
        for w in result.warnings
    )
    confidence_cap = None
    for prior in context.prior_results:
        if prior.tool is ToolName.VERIFICATION and prior.operation == "verify_evidence":
            cap = prior.data.get("confidence_cap")
            if isinstance(cap, (int, float)):
                confidence_cap = float(cap)

    if operation == "classify":
        entity_id = str(
            parameters.get("entity_id")
            or parameters.get("transaction_id")
            or (
                context.filters.transaction_ids[0] if context.filters.transaction_ids else "UNKNOWN"
            )
        )
        classified = classify_transaction_risk(
            entity_id=entity_id,
            anomaly_payload=anomaly,
            graph_findings=graph,
            policy=policy,
            evidence_ids=evidence_ids,
            confidence_cap=confidence_cap,
            insufficient_data=insufficient,
        )
        return make_result(
            tool=ToolName.RISK_CLASSIFICATION,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={
                "entity_type": classified.entity_type,
                "entity_id": classified.entity_id,
                "risk_score": classified.risk_score,
                "risk_level": classified.risk_level.value,
                "confidence": classified.confidence,
                "ml_score": classified.ml_score,
                "contributing_signals": classified.contributing_signals,
                "reasons": classified.reasons,
                "evidence_ids": classified.evidence_ids,
                "policy_version": classified.policy_version,
                "insufficient_data": insufficient,
            },
            warnings=classified.warnings,
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    if operation == "classify_customer":
        customer_id = str(
            parameters.get("entity_id")
            or parameters.get("customer_id")
            or (context.filters.customer_ids[0] if context.filters.customer_ids else "UNKNOWN")
        )
        # Prefer explicit parameter lists; else derive from a single transaction classify.
        txn_risks = list(parameters.get("transaction_risks") or [])
        rule_events = list(parameters.get("rule_events") or [])
        if not txn_risks and anomaly:
            # Seed one synthetic txn risk from current anomaly classification.
            seed = classify_transaction_risk(
                entity_id=customer_id,
                anomaly_payload=anomaly,
                graph_findings=graph,
                policy=policy,
                evidence_ids=evidence_ids,
                confidence_cap=confidence_cap,
                insufficient_data=insufficient,
            )
            txn_risks = [
                {"transaction_id": f"derived:{customer_id}", "risk_score": seed.risk_score}
            ]
            rule_events = [
                {
                    "rule_id": item.get("rule_id") or "rule",
                    "severity": item.get("severity") or "medium",
                    "age_days": 0,
                }
                for item in seed.contributing_signals
                if item.get("type") == "rule"
            ]
        profile_score = parameters.get("profile_score")
        context_score = parameters.get("context_score")
        rolled = rollup_customer_risk(
            customer_id=customer_id,
            transaction_risks=txn_risks,
            rule_events=rule_events,
            profile_score=float(profile_score) if profile_score is not None else None,
            context_score=float(context_score) if context_score is not None else None,
            policy=policy,
            evidence_ids=evidence_ids,
        )
        return make_result(
            tool=ToolName.RISK_CLASSIFICATION,
            operation=operation,
            status=ToolStatus.SUCCESS,
            scope=context.filters,
            data={
                "entity_type": "customer",
                "entity_id": rolled.entity_id,
                "risk_score": rolled.risk_score,
                "risk_level": rolled.risk_level.value,
                "confidence": rolled.confidence,
                "ml_score": None,
                "event_peak": rolled.event_peak,
                "pattern_breadth": rolled.pattern_breadth,
                "profile_score": rolled.profile_score,
                "context_score": rolled.context_score,
                "composite": rolled.composite,
                "contributing_signals": [
                    {"type": "rule", "rule_id": rid} for rid in rolled.contributing_rule_ids
                ],
                "reasons": rolled.reasons,
                "evidence_ids": rolled.evidence_ids,
                "policy_version": rolled.policy_version,
                "rollup_method": rolled.rollup_method,
                "decay_values": rolled.decay_values,
                "contributing_transaction_ids": rolled.contributing_transaction_ids,
                "insufficient_data": insufficient,
                "context_only": (
                    rolled.event_peak < 40
                    and rolled.pattern_breadth < 40
                    and rolled.profile_score < 40
                    and rolled.context_score > 0
                ),
            },
            warnings=rolled.warnings,
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    raise ValueError(f"unknown risk_classification operation: {operation}")


def handle_escalation(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    policy = _policy(context)
    provenance = ToolProvenance(
        source="escalation",
        query_or_version="escalation.v1",
        policy_version=policy.version,
    )
    if operation != "recommend":
        raise ValueError(f"unknown escalation operation: {operation}")
    if not context.settings.risk_enabled:
        return make_result(
            tool=ToolName.ESCALATION,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["RISK_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    risk = _latest_consistent_or_risk(context.prior_results)
    if risk is None:
        return make_result(
            tool=ToolName.ESCALATION,
            operation=operation,
            status=ToolStatus.FAILED,
            scope=context.filters,
            duration_ms=timer.ms(),
            provenance=provenance,
            error=ToolError(
                code="MISSING_VERIFIED_RISK",
                message="Escalation requires verified risk",
                retryable=False,
            ),
        )

    from backend.app.domain.enums import RiskLevel

    window_end = context.as_of
    window_start = context.as_of - timedelta(days=int(policy.customer_rollup.lookback_days))
    recommendation = recommend_escalation(
        entity_type=str(risk.get("entity_type") or "customer"),
        entity_id=str(risk.get("entity_id") or "UNKNOWN"),
        risk_score=float(risk["risk_score"]),
        risk_level=RiskLevel(str(risk["risk_level"])),
        confidence=float(risk.get("confidence") or 0.5),
        reasons=list(risk.get("reasons") or []),
        evidence_ids=list(risk.get("evidence_ids") or []),
        policy=policy,
        window_start=window_start,
        window_end=window_end,
    )
    alert_id = None
    created = False
    if recommendation.should_create_alert:
        severity = {
            "LOW": "low",
            "MEDIUM": "medium",
            "HIGH": "high",
        }[recommendation.risk_level.value]
        # Prefer verified score mapping: still uses create_alert API but finding is Phase 8.
        request = AlertCreateRequest(
            entity_type=EntityType(str(risk.get("entity_type") or "customer")),
            entity_id=str(risk.get("entity_id") or "UNKNOWN"),
            investigation_id=context.investigation_id,
            finding_code=recommendation.finding_code,
            severity=severity,  # type: ignore[arg-type]
            evidence_snapshot_ref=f"phase8:{context.request_id or 'adhoc'}",
            policy_version=policy.version,
            investigation_window_start=window_start,
            investigation_window_end=window_end,
            request_id=context.request_id or f"esc-{context.as_of.timestamp()}",
        )
        alert, created = alert_service.create_alert(context.session, request)
        # Overlay verified risk onto the alert row (provisional map may differ).
        alert.risk_score = recommendation.snapshot["risk_score"]
        alert.risk_tier = recommendation.risk_level.value
        alert.escalation_action = recommendation.escalation_action.value
        context.session.flush()
        alert_id = alert.alert_id

    return make_result(
        tool=ToolName.ESCALATION,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data={
            **recommendation.snapshot,
            "wording": recommendation.wording,
            "alert_id": alert_id,
            "alert_created": created,
        },
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def handle_explanation(
    context: ToolContext,
    operation: str,
    parameters: dict[str, Any],
) -> Any:
    timer = Timer()
    provenance = ToolProvenance(
        source="explanation",
        query_or_version="explanation.v1",
        policy_version=context.policy.version,
    )
    if operation != "explain":
        raise ValueError(f"unknown explanation operation: {operation}")
    if not context.settings.explanation_enabled:
        return make_result(
            tool=ToolName.EXPLANATION,
            operation=operation,
            status=ToolStatus.SKIPPED,
            scope=context.filters,
            warnings=["EXPLANATION_DISABLED"],
            duration_ms=timer.ms(),
            provenance=provenance,
        )

    risk = _latest_consistent_or_risk(context.prior_results)
    escalation = None
    for prior in reversed(context.prior_results):
        if prior.tool is ToolName.ESCALATION and prior.status is ToolStatus.SUCCESS:
            escalation = prior.data
            break
    if risk is None:
        return make_result(
            tool=ToolName.EXPLANATION,
            operation=operation,
            status=ToolStatus.FAILED,
            scope=context.filters,
            duration_ms=timer.ms(),
            provenance=provenance,
            error=ToolError(
                code="MISSING_VERIFIED_RISK",
                message="Explanation requires verified risk",
                retryable=False,
            ),
        )

    payload = {
        "entity_id": risk.get("entity_id"),
        "entity_type": risk.get("entity_type"),
        "risk_score": risk.get("risk_score"),
        "risk_level": risk.get("risk_level"),
        "confidence": risk.get("confidence"),
        "reasons": risk.get("reasons") or [],
        "evidence_ids": risk.get("evidence_ids") or [],
        "warnings": risk.get("warnings") or [],
        "contributing_signals": risk.get("contributing_signals") or [],
        "escalation_action": (escalation or {}).get("escalation_action") or "monitor",
        "ml_score": risk.get("ml_score"),
    }
    explanation = generate_explanation(payload, settings=context.settings)
    return make_result(
        tool=ToolName.EXPLANATION,
        operation=operation,
        status=ToolStatus.SUCCESS,
        scope=context.filters,
        data=explanation,
        warnings=["GROUNDED_EVIDENCE_ONLY"],
        duration_ms=timer.ms(),
        provenance=provenance,
    )


def _latest_risk_payload(results: list[Any]) -> dict[str, Any] | None:
    for result in reversed(results):
        if result.tool is ToolName.RISK_CLASSIFICATION and result.status is ToolStatus.SUCCESS:
            return dict(result.data)
    return None


def _latest_consistent_or_risk(results: list[Any]) -> dict[str, Any] | None:
    """Only dual-verified (Stage-2 success) risk may escalate or explain."""
    for result in reversed(results):
        if (
            result.tool is ToolName.VERIFICATION
            and result.operation == "verify_risk_consistency"
            and result.status is ToolStatus.SUCCESS
        ):
            return dict(result.data)
    return None
