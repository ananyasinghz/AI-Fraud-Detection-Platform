"""Alert lifecycle: idempotent create, validated transitions, append-only events."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import cast
from uuid import uuid4

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.errors import AppError
from backend.app.data.models import Alert, AlertEvent
from backend.app.domain.api import AlertCreateRequest, AlertPatchRequest, AlertStatus
from backend.app.services.alert_packs import write_alert_pack
from backend.app.services.provisional_risk import provisional_risk_from_severity

ALLOWED_TRANSITIONS: dict[AlertStatus, frozenset[AlertStatus]] = {
    "open": frozenset({"in_review", "escalated", "dismissed", "closed"}),
    "in_review": frozenset({"escalated", "dismissed", "closed"}),
    "escalated": frozenset({"in_review", "dismissed", "closed"}),
    "dismissed": frozenset({"closed"}),
    "closed": frozenset(),
}


def build_idempotency_key(request: AlertCreateRequest) -> str:
    raw = "|".join(
        [
            request.entity_type.value,
            request.entity_id,
            request.finding_code,
            request.policy_version,
            request.investigation_window_start.astimezone(UTC).isoformat(),
            request.investigation_window_end.astimezone(UTC).isoformat(),
        ]
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def create_alert(session: Session, request: AlertCreateRequest) -> tuple[Alert, bool]:
    """Create an alert or return the existing row for the same idempotency key."""
    key = build_idempotency_key(request)
    existing = session.scalar(select(Alert).where(Alert.idempotency_key == key))
    if existing is not None:
        return existing, False

    if request.investigation_window_end <= request.investigation_window_start:
        raise AppError(
            code="INVALID_WINDOW",
            message="investigation_window_end must be after investigation_window_start",
            status_code=422,
        )

    risk_score, risk_tier, escalation = provisional_risk_from_severity(request.severity)
    now = datetime.now(tz=UTC)
    alert = Alert(
        alert_id=f"alert-{uuid4().hex}",
        investigation_id=request.investigation_id,
        entity_type=request.entity_type.value,
        entity_id=request.entity_id,
        status="open",
        risk_score=risk_score,
        risk_tier=risk_tier.value,
        escalation_action=escalation.value,
        evidence_snapshot_ref=request.evidence_snapshot_ref,
        policy_version=request.policy_version,
        idempotency_key=key,
        created_at=now,
        updated_at=now,
    )
    session.add(alert)
    session.flush()

    if request.case_pack is not None:
        settings = get_settings()
        ref = write_alert_pack(settings.data_dir, alert.alert_id, request.case_pack)
        alert.evidence_snapshot_ref = ref
        session.flush()

    session.add(
        AlertEvent(
            alert_id=alert.alert_id,
            timestamp=now,
            from_status=None,
            to_status="open",
            reviewer_id="system",
            reason=f"created finding {request.finding_code}",
            request_id=request.request_id,
            evidence_version="v1",
            risk_policy_version=request.policy_version,
        )
    )
    session.flush()
    return alert, True


def get_alert(session: Session, alert_id: str) -> Alert | None:
    return session.get(Alert, alert_id)


def list_alert_events(session: Session, alert_id: str) -> list[AlertEvent]:
    statement: Select[tuple[AlertEvent]] = (
        select(AlertEvent)
        .where(AlertEvent.alert_id == alert_id)
        .order_by(AlertEvent.timestamp.asc(), AlertEvent.event_id.asc())
    )
    return list(session.scalars(statement))


def list_alerts(
    session: Session,
    *,
    status: AlertStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Alert], int]:
    filters = []
    if status is not None:
        filters.append(Alert.status == status)
    count_statement = select(func.count()).select_from(Alert)
    list_statement = select(Alert)
    if filters:
        count_statement = count_statement.where(*filters)
        list_statement = list_statement.where(*filters)
    total = int(session.scalar(count_statement) or 0)
    rows = list(
        session.scalars(
            list_statement.order_by(Alert.created_at.desc(), Alert.alert_id.asc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def transition_alert(session: Session, alert_id: str, request: AlertPatchRequest) -> Alert:
    if not request.reason.strip():
        raise AppError(
            code="REASON_REQUIRED",
            message="status transitions require a non-empty reason",
            status_code=422,
        )
    alert = get_alert(session, alert_id)
    if alert is None:
        raise AppError(code="ALERT_NOT_FOUND", message="alert not found", status_code=404)

    current = cast(AlertStatus, alert.status)
    if current not in ALLOWED_TRANSITIONS:
        raise AppError(
            code="INVALID_STATUS",
            message=f"alert has unsupported status: {current}",
            status_code=409,
        )
    allowed = ALLOWED_TRANSITIONS[current]
    if request.status not in allowed:
        raise AppError(
            code="INVALID_TRANSITION",
            message=f"cannot transition from {current} to {request.status}",
            status_code=409,
            details={"from": current, "to": request.status, "allowed": sorted(allowed)},
        )

    now = datetime.now(tz=UTC)
    session.add(
        AlertEvent(
            alert_id=alert.alert_id,
            timestamp=now,
            from_status=current,
            to_status=request.status,
            reviewer_id=request.reviewer_id,
            reason=request.reason,
            request_id=request.request_id,
            evidence_version=request.evidence_version,
            risk_policy_version=alert.policy_version,
        )
    )
    alert.status = request.status
    alert.updated_at = now
    session.flush()
    return alert
