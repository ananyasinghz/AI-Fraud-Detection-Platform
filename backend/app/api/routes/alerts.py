"""Alert create, queue, detail, and transition routes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from backend.app.api.dependencies import SessionDep
from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.data.models import Alert, AlertEvent
from backend.app.domain.api import (
    AlertCreateRequest,
    AlertEventResponse,
    AlertPatchRequest,
    AlertResponse,
    AlertStatus,
)
from backend.app.domain.base import ContractModel
from backend.app.domain.enums import EscalationAction, RiskLevel
from backend.app.services import alerts as alert_service
from backend.app.services.alert_packs import read_alert_pack_from_ref

router = APIRouter(tags=["alerts"])


class AlertListResponse(ContractModel):
    items: list[AlertResponse]
    total: int
    limit: int
    offset: int


def _event_response(event: AlertEvent) -> AlertEventResponse:
    return AlertEventResponse(
        event_id=event.event_id,
        alert_id=event.alert_id,
        timestamp=event.timestamp,
        from_status=event.from_status,
        to_status=event.to_status,
        reviewer_id=event.reviewer_id,
        reason=event.reason,
        request_id=event.request_id,
        evidence_version=event.evidence_version,
        risk_policy_version=event.risk_policy_version,
    )


def _alert_response(alert: Alert, history: list[AlertEvent]) -> AlertResponse:
    settings = get_settings()
    case_pack = read_alert_pack_from_ref(settings.data_dir, alert.evidence_snapshot_ref)
    if case_pack is None:
        case_pack = read_alert_pack_from_ref(settings.data_dir, f"pack:{alert.alert_id}")
    return AlertResponse(
        alert_id=alert.alert_id,
        investigation_id=alert.investigation_id,
        entity_type=alert.entity_type,
        entity_id=alert.entity_id,
        status=alert.status,  # type: ignore[arg-type]
        risk_score=alert.risk_score,
        risk_tier=RiskLevel(alert.risk_tier),
        escalation_action=EscalationAction(alert.escalation_action),
        evidence_snapshot_ref=alert.evidence_snapshot_ref,
        policy_version=alert.policy_version,
        idempotency_key=alert.idempotency_key,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
        history=[_event_response(item) for item in history],
        case_pack=case_pack,
    )


@router.post("/alerts", response_model=AlertResponse)
async def create_alert(body: AlertCreateRequest, session: SessionDep) -> AlertResponse:
    alert, _created = alert_service.create_alert(session, body)
    history = alert_service.list_alert_events(session, alert.alert_id)
    return _alert_response(alert, history)


@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    session: SessionDep,
    status: Annotated[AlertStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[Literal["created_at_desc"], Query()] = "created_at_desc",
) -> AlertListResponse:
    del sort
    rows, total = alert_service.list_alerts(session, status=status, limit=limit, offset=offset)
    items = [
        _alert_response(alert, alert_service.list_alert_events(session, alert.alert_id))
        for alert in rows
    ]
    return AlertListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/alerts/{alert_id}", response_model=AlertResponse)
async def get_alert(alert_id: str, session: SessionDep) -> AlertResponse:
    alert = alert_service.get_alert(session, alert_id)
    if alert is None:
        raise AppError(code="ALERT_NOT_FOUND", message="alert not found", status_code=404)
    history = alert_service.list_alert_events(session, alert_id)
    return _alert_response(alert, history)


@router.patch("/alerts/{alert_id}", response_model=AlertResponse)
async def patch_alert(
    alert_id: str,
    body: AlertPatchRequest,
    session: SessionDep,
) -> AlertResponse:
    alert = alert_service.transition_alert(session, alert_id, body)
    history = alert_service.list_alert_events(session, alert_id)
    return _alert_response(alert, history)
