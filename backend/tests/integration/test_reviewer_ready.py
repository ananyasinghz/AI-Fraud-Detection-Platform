"""Reviewer-ready alert case packs and customer detail enrichment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend.app.domain.api import (
    AlertResponse,
    CustomerDetailResponse,
    CustomerTransactionSummary,
)
from backend.app.domain.enums import EscalationAction, RiskLevel
from backend.tests.integration.test_phase3_api import AS_OF
from backend.tests.integration.test_phase3_api import api_client as api_client_fixture

# Re-export so pytest can inject the Phase 3 api_client fixture into this module.
api_client = api_client_fixture


def test_alert_create_with_case_pack_round_trip(api_client: TestClient) -> None:
    pack = {
        "pack_version": "alert_case_pack.v1",
        "query": "Is customer C1 suspicious?",
        "request_id": "req-pack-1",
        "flagged_result": {
            "result_type": "flagged",
            "entity_type": "customer",
            "entity_id": "C1",
            "risk_score": 72.0,
            "risk_level": "HIGH",
            "confidence": 0.9,
            "reasons": ["velocity"],
            "escalation_action": "escalate",
            "evidence_refs": ["ev-1"],
        },
        "explanation": {
            "summary": "Elevated velocity",
            "reasons": ["Multiple cash deposits"],
            "source": "template",
            "riskLevel": "HIGH",
            "riskScore": 72,
        },
        "supporting_evidence": [],
    }
    payload = {
        "entity_type": "customer",
        "entity_id": "C1",
        "finding_code": "UI_MANUAL_ALERT",
        "severity": "high",
        "evidence_snapshot_ref": "ui:C1",
        "policy_version": "risk_scoring.v1",
        "investigation_window_start": AS_OF.isoformat(),
        "investigation_window_end": (AS_OF + timedelta(days=7)).isoformat(),
        "request_id": "alert-pack-create-1",
        "case_pack": pack,
    }
    created = api_client.post("/api/v1/alerts", json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["evidence_snapshot_ref"].startswith("pack:")
    assert body["case_pack"] is not None
    assert body["case_pack"]["query"] == pack["query"]
    assert body["case_pack"]["explanation"]["summary"] == "Elevated velocity"

    detail = api_client.get(f"/api/v1/alerts/{body['alert_id']}")
    assert detail.status_code == 200
    assert detail.json()["case_pack"]["request_id"] == "req-pack-1"

    listed = api_client.get("/api/v1/alerts", params={"limit": 50})
    assert listed.status_code == 200
    match = next(item for item in listed.json()["items"] if item["alert_id"] == body["alert_id"])
    assert match["case_pack"]["pack_version"] == "alert_case_pack.v1"


def test_customer_detail_includes_recent_transactions(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/customers/C1")
    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "C1"
    assert "recent_transactions" in body
    assert isinstance(body["recent_transactions"], list)
    assert len(body["recent_transactions"]) >= 1
    tx = body["recent_transactions"][0]
    assert "transaction_id" in tx
    assert "amount_minor" in tx
    assert "occurred_at" in tx
    assert "transaction_type" in tx


def test_customer_detail_response_contract() -> None:
    as_of = datetime(2026, 7, 25, tzinfo=UTC)
    detail = CustomerDetailResponse(
        customer_id="C1",
        created_at=as_of,
        status="active",
        segment="retail",
        residence_country="US",
        kyc_risk_rating="medium",
        recent_transactions=[
            CustomerTransactionSummary(
                transaction_id="T1",
                amount_minor=5000,
                currency="USD",
                occurred_at=as_of,
                transaction_type="wire",
            )
        ],
    )
    assert detail.segment == "retail"
    assert detail.recent_transactions[0].amount_minor == 5000


def test_alert_response_accepts_case_pack() -> None:
    now = datetime(2026, 7, 25, tzinfo=UTC)
    body = AlertResponse(
        alert_id="alert-1",
        investigation_id=None,
        entity_type="customer",
        entity_id="C1",
        status="open",
        risk_score=10.0,
        risk_tier=RiskLevel.LOW,
        escalation_action=EscalationAction.MONITOR,
        evidence_snapshot_ref="pack:alert-1",
        policy_version="risk_scoring.v1",
        idempotency_key="abc",
        created_at=now,
        updated_at=now,
        history=[],
        case_pack={"pack_version": "alert_case_pack.v1"},
    )
    assert body.case_pack is not None
