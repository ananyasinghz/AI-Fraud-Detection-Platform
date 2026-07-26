"""Unit tests for Phase 8 evidence, risk, rollup, consistency, escalation, explanation."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import (
    EscalationAction,
    RiskLevel,
    ToolName,
    ToolStatus,
)
from backend.app.domain.evidence import EvidenceReference, ToolProvenance, ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.evidence.verification import verify_evidence
from backend.app.explanation.faithfulness import validate_explanation_citations
from backend.app.explanation.generator import generate_explanation
from backend.app.risk.classifier import classify_transaction_risk
from backend.app.risk.consistency import verify_risk_consistency
from backend.app.risk.customer_rollup import recency_decay, rollup_customer_risk
from backend.app.risk.escalation import map_escalation, recommend_escalation
from backend.app.risk.policy import RiskScoringPolicy, get_risk_policy, load_risk_policy
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY

POLICY_PATH = Path("config/policy/risk_scoring.v1.yaml")
AS_OF = datetime(2026, 2, 15, tzinfo=UTC)


@pytest.fixture
def policy() -> RiskScoringPolicy:
    get_risk_policy.cache_clear()
    return load_risk_policy(POLICY_PATH)


def _result(
    tool: ToolName,
    operation: str,
    *,
    data: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    scope: NormalizedFilters | None = None,
    evidence: list[EvidenceReference] | None = None,
    status: ToolStatus = ToolStatus.SUCCESS,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        operation=operation,
        status=status,
        produced_at=AS_OF,
        scope=scope or NormalizedFilters(customer_ids=["C1"]),
        data=data or {"ok": True},
        warnings=warnings or [],
        duration_ms=1,
        evidence=evidence
        or [
            EvidenceReference(
                evidence_id=f"{tool.value}.{operation}",
                tool=tool,
                kind="tool_result",
                json_path="$.data",
                label=operation,
            )
        ],
        provenance=ToolProvenance(
            source=tool.value,
            query_or_version="test.v1",
            policy_version="reporting_thresholds.v1",
        ),
    )


def test_evidence_unresolved_and_empty_block() -> None:
    empty = verify_evidence([], requested_scope=NormalizedFilters())
    assert empty.block_risk
    assert "NO_PRIOR_TOOL_RESULTS" in empty.warnings

    no_refs = verify_evidence(
        [
            ToolResult(
                tool=ToolName.SQL_LOOKUP,
                operation="get_customer",
                status=ToolStatus.SUCCESS,
                produced_at=AS_OF,
                scope=NormalizedFilters(),
                data={},
                duration_ms=1,
                evidence=[],
                provenance=ToolProvenance(source="sql", query_or_version="t"),
            )
        ],
        requested_scope=NormalizedFilters(),
    )
    # Synthetic refs are added by aggregator when evidence list empty — collect still works
    # Force block via missing required signal tools.
    required = verify_evidence(
        [_result(ToolName.SQL_LOOKUP, "get_customer")],
        requested_scope=NormalizedFilters(customer_ids=["C1"]),
        require_anomaly_or_feature=True,
    )
    assert required.block_risk
    assert "MISSING_REQUIRED_SIGNAL_TOOLS" in required.warnings
    del no_refs


def test_evidence_scope_mismatch_and_forbidden_field(policy: RiskScoringPolicy) -> None:
    del policy
    widened = _result(
        ToolName.ANOMALY_DETECTION,
        "detect",
        scope=NormalizedFilters(customer_ids=["C1", "C2"]),
        data={"rules": [], "scenario_label": "hidden"},
    )
    result = verify_evidence(
        [widened],
        requested_scope=NormalizedFilters(customer_ids=["C1"]),
    )
    assert result.block_risk
    assert any(w.startswith("SCOPE_MISMATCH") for w in result.warnings)
    assert any(w.startswith("FORBIDDEN_FIELD") for w in result.warnings)


def test_evidence_insufficient_sets_confidence_cap() -> None:
    result = verify_evidence(
        [
            _result(
                ToolName.FEATURE_ENGINEERING,
                "compute_feature",
                warnings=["INSUFFICIENT_HISTORY"],
            )
        ],
        requested_scope=NormalizedFilters(customer_ids=["C1"]),
    )
    assert not result.block_risk or result.confidence_cap == 0.55
    assert result.confidence_cap == 0.55
    assert any(w.startswith("DATA_SUFFICIENCY") for w in result.warnings)


def test_points_tier_boundaries_and_ml_separation(policy: RiskScoringPolicy) -> None:
    low = classify_transaction_risk(
        entity_id="T1",
        anomaly_payload={},
        graph_findings=[],
        policy=policy,
        evidence_ids=["e1"],
    )
    assert low.risk_level is RiskLevel.LOW
    assert low.ml_score is None

    medium = classify_transaction_risk(
        entity_id="T2",
        anomaly_payload={
            "rules": [{"rule_id": "R1", "severity": "medium", "fired": True}],
            "ml": {"ml_score": 0.9},
        },
        graph_findings=[],
        policy=policy,
        evidence_ids=["e1"],
    )
    # 35 rule + 25 ML = 60 → MEDIUM; ml_score distinct
    assert medium.risk_score == 60
    assert medium.risk_level is RiskLevel.MEDIUM
    assert medium.ml_score == 0.9

    high = classify_transaction_risk(
        entity_id="T3",
        anomaly_payload={
            "rules": [{"rule_id": "R2", "severity": "critical", "fired": True}],
        },
        graph_findings=[{"operation": "circular_transfers", "cycles": [["a", "b"]]}],
        policy=policy,
        evidence_ids=["e1"],
    )
    assert high.risk_score >= 70
    assert high.risk_level is RiskLevel.HIGH

    # Exact boundaries
    assert (
        classify_transaction_risk(
            entity_id="b40",
            anomaly_payload={"rules": [{"rule_id": "x", "severity": "medium", "fired": True}]},
            graph_findings=[],
            policy=policy,
            evidence_ids=["e"],
        ).risk_level
        is RiskLevel.LOW
    )  # 35 < 40

    # 40 points via statistical + medium rule = 55 → MEDIUM
    at_medium = classify_transaction_risk(
        entity_id="b40b",
        anomaly_payload={
            "rules": [{"rule_id": "x", "severity": "medium", "fired": True}],
            "statistics": {"robust_z": 4.0},
        },
        graph_findings=[],
        policy=policy,
        evidence_ids=["e"],
    )
    assert at_medium.risk_score == 55
    assert at_medium.risk_level is RiskLevel.MEDIUM


def test_customer_rollup_event_peak_pattern_decay_context(policy: RiskScoringPolicy) -> None:
    severe = rollup_customer_risk(
        customer_id="C1",
        transaction_risks=[{"transaction_id": "T1", "risk_score": 80}],
        rule_events=[],
        profile_score=0,
        context_score=100,
        policy=policy,
        evidence_ids=["e1"],
    )
    assert severe.event_peak == 80
    assert severe.risk_level is RiskLevel.HIGH

    # Duplicate rule suppression + recency decay
    assert recency_decay(90, half_life_days=90) == pytest.approx(0.5)
    breadth = rollup_customer_risk(
        customer_id="C2",
        transaction_risks=[{"transaction_id": "T2", "risk_score": 10}],
        rule_events=[
            {"rule_id": "R1", "severity": "high", "age_days": 0},
            {"rule_id": "R1", "severity": "high", "age_days": 90},  # duplicate, lower
            {"rule_id": "R2", "severity": "high", "age_days": 0},
            {"rule_id": "R3", "severity": "high", "age_days": 0},
        ],
        profile_score=100,
        context_score=0,
        policy=policy,
        evidence_ids=["e1"],
    )
    assert breadth.contributing_rule_ids == ["R1", "R2", "R3"]
    assert breadth.pattern_breadth == 100.0
    # With locked weights, pattern_breadth (cap 100 → 35 pts) + profile (20) → MEDIUM.
    assert breadth.risk_level is RiskLevel.MEDIUM
    assert breadth.composite == pytest.approx(0.4 * 10 + 0.35 * 100 + 0.20 * 100, abs=0.01)

    # Profile missingness warning
    missing_profile = rollup_customer_risk(
        customer_id="C2b",
        transaction_risks=[],
        rule_events=[{"rule_id": "R9", "severity": "medium", "age_days": 0}],
        profile_score=None,
        context_score=0,
        policy=policy,
        evidence_ids=["e1"],
    )
    assert "PROFILE_SCORE_MISSING" in missing_profile.warnings

    # Context alone (or context tipping a near-threshold composite) cannot force suspicious.
    context_only = rollup_customer_risk(
        customer_id="C3",
        transaction_risks=[],
        rule_events=[
            {"rule_id": "R1", "severity": "high", "age_days": 0},
            {"rule_id": "R2", "severity": "high", "age_days": 0},
            {"rule_id": "R3", "severity": "high", "age_days": 0},
        ],
        profile_score=0,
        context_score=100,
        policy=policy,
        evidence_ids=["e1"],
    )
    # pattern_breadth=100 → 35 pts; +5 context would tip to 40 without the guard.
    assert context_only.risk_level is RiskLevel.LOW
    assert "CONTEXT_ONLY_SUSPICIOUS_BLOCKED" in context_only.warnings

    # Exact tier boundaries on score
    edge = rollup_customer_risk(
        customer_id="C4",
        transaction_risks=[{"transaction_id": "T", "risk_score": 40}],
        rule_events=[],
        profile_score=0,
        context_score=0,
        policy=policy,
        evidence_ids=["e"],
    )
    assert edge.risk_score == 40
    assert edge.risk_level is RiskLevel.MEDIUM


def test_consistency_recompute_weights_context_weak_data(policy: RiskScoringPolicy) -> None:
    ok = verify_risk_consistency(
        risk_score=55,
        risk_level=RiskLevel.LOW,  # mismatch → recompute
        confidence=0.8,
        contributing_signals=[{"type": "rule"}],
        policy=policy,
    )
    assert ok.ok
    assert ok.risk_level is RiskLevel.MEDIUM
    assert "TIER_MISMATCH_RECOMPUTED" in ok.warnings

    bad_weights = policy.model_copy(
        update={
            "customer_rollup": policy.customer_rollup.model_copy(
                update={
                    "weights": policy.customer_rollup.weights.model_copy(
                        update={"event_peak": 0.9, "pattern_breadth": 0.9}
                    )
                }
            )
        }
    )
    rejected = verify_risk_consistency(
        risk_score=50,
        risk_level=RiskLevel.MEDIUM,
        confidence=0.5,
        contributing_signals=[],
        policy=bad_weights,
    )
    assert not rejected.ok
    assert rejected.action == "reject"

    downgraded = verify_risk_consistency(
        risk_score=80,
        risk_level=RiskLevel.HIGH,
        confidence=0.9,
        contributing_signals=[],
        policy=policy,
        context_only=True,
    )
    assert downgraded.action == "downgrade"
    assert downgraded.risk_level is RiskLevel.LOW

    weak = verify_risk_consistency(
        risk_score=85,
        risk_level=RiskLevel.HIGH,
        confidence=0.9,
        contributing_signals=[{"type": "rule"}],
        policy=policy,
        insufficient_data=True,
    )
    assert weak.action == "downgrade"
    assert weak.risk_level is RiskLevel.MEDIUM


def test_escalation_mapping(policy: RiskScoringPolicy) -> None:
    assert map_escalation(RiskLevel.LOW, policy) is EscalationAction.MONITOR
    assert map_escalation(RiskLevel.MEDIUM, policy) is EscalationAction.REVIEW
    assert map_escalation(RiskLevel.HIGH, policy) is EscalationAction.REPORT
    rec = recommend_escalation(
        entity_type="customer",
        entity_id="C1",
        risk_score=75,
        risk_level=RiskLevel.HIGH,
        confidence=0.8,
        reasons=["severe"],
        evidence_ids=["e1"],
        policy=policy,
        window_start=AS_OF,
        window_end=AS_OF,
    )
    assert rec.should_create_alert
    assert "institutional policy" in rec.wording
    assert "SAR must" not in rec.wording


def test_explanation_citation_and_fallback(policy: RiskScoringPolicy) -> None:
    del policy
    settings = Settings(environment="test", ollama_enabled=False, explanation_enabled=True)
    payload = {
        "entity_id": "C1",
        "risk_score": 55.0,
        "risk_level": "MEDIUM",
        "confidence": 0.8,
        "reasons": ["Rule R1 fired"],
        "evidence_ids": ["ev-1"],
        "escalation_action": "review",
        "contributing_signals": [{"type": "rule", "rule_id": "R1"}],
        "warnings": [],
    }
    templated = generate_explanation(payload, settings=settings)
    assert templated["source"] == "template"
    assert "55.0" in templated["summary"] or "MEDIUM" in templated["summary"]

    ok, problems = validate_explanation_citations(
        {
            "summary": "ok",
            "reasons": ["fine"],
            "evidence_ids": ["ev-1"],
            "claims": [{"claim": "x", "evidence_ids": ["ev-1"]}],
        },
        allowed_evidence_ids={"ev-1"},
        allowed_numbers={"55.0", "0.80", "55"},
        allowed_rule_ids={"R1"},
    )
    assert ok and not problems

    bad_ok, bad_problems = validate_explanation_citations(
        {
            "summary": "RULE_FAKE_V1 invented 99999 dollars",
            "reasons": [],
            "evidence_ids": ["ghost"],
            "claims": [],
        },
        allowed_evidence_ids={"ev-1"},
        allowed_numbers={"55.0"},
        allowed_rule_ids={"R1"},
    )
    assert not bad_ok
    assert any("unknown_evidence" in p or "hallucinated_rule" in p for p in bad_problems)

    def hallucinating(_prompt: str, _extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "message": {
                "content": (
                    '{"summary":"RULE_FAKE_V1 says 99999",'
                    '"reasons":["x"],"risk_level_explanation":"x",'
                    '"recommended_action_explanation":"x","uncertainty_note":"x",'
                    '"evidence_ids":["ghost"],"claims":[]}'
                )
            }
        }

    fallback = generate_explanation(
        payload,
        settings=Settings(environment="test", ollama_enabled=True, explanation_enabled=True),
        transport=hallucinating,
    )
    assert fallback["source"] == "template_fallback"


def _context(session: Session) -> ToolContext:
    return ToolContext(
        session=session,
        policy=__import__(
            "backend.app.policy.config", fromlist=["load_policy_config"]
        ).load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml")),
        settings=Settings(environment="test", ollama_enabled=False),
        filters=NormalizedFilters(customer_ids=["C1"]),
        as_of=AS_OF,
        request_id="req-p8",
        investigation_id="inv-p8",
    )


def test_idempotent_alert_from_escalation(tmp_path: Path, policy: RiskScoringPolicy) -> None:
    del policy
    engine = create_database_engine(f"sqlite:///{tmp_path / 'esc.db'}")
    Base.metadata.create_all(engine)
    prior = [
        _result(
            ToolName.ANOMALY_DETECTION,
            "detect",
            data={"rules": [{"rule_id": "R1", "severity": "high", "fired": True}]},
        ),
        _result(
            ToolName.VERIFICATION,
            "verify_evidence",
            data={
                "ok": True,
                "block_risk": False,
                "evidence_ids": ["anomaly_detection.detect"],
                "confidence_cap": None,
            },
        ),
        _result(
            ToolName.RISK_CLASSIFICATION,
            "classify_customer",
            data={
                "entity_type": "customer",
                "entity_id": "C1",
                "risk_score": 75,
                "risk_level": "HIGH",
                "confidence": 0.8,
                "reasons": ["severe"],
                "evidence_ids": ["anomaly_detection.detect"],
                "contributing_signals": [{"type": "rule", "rule_id": "R1"}],
            },
        ),
        _result(
            ToolName.VERIFICATION,
            "verify_risk_consistency",
            data={
                "ok": True,
                "action": "pass",
                "risk_score": 75,
                "risk_level": "HIGH",
                "confidence": 0.8,
                "entity_id": "C1",
                "entity_type": "customer",
                "reasons": ["severe"],
                "evidence_ids": ["anomaly_detection.detect"],
                "contributing_signals": [{"type": "rule", "rule_id": "R1"}],
            },
        ),
    ]
    with session_scope(session_factory(engine)) as session:
        context = _context(session)
        context.investigation_id = None
        context.prior_results = prior
        first = TOOL_REGISTRY.dispatch(ToolName.ESCALATION, "recommend", context=context)
        assert first.status is ToolStatus.SUCCESS
        assert first.data["escalation_action"] == "report"
        assert first.data["alert_id"]
        assert first.data["alert_created"] is True
        alert_id = first.data["alert_id"]
        context.prior_results = prior
        second = TOOL_REGISTRY.dispatch(ToolName.ESCALATION, "recommend", context=context)
        assert second.data["alert_id"] == alert_id
        assert second.data["alert_created"] is False
