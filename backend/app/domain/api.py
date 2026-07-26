"""HTTP request/response contracts for Phase 3-6 APIs."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import (
    EntityType,
    EscalationAction,
    IntentType,
    RiskLevel,
    RouteType,
)
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import ParsedIntent
from backend.app.domain.plan import ValidatedPlan
from backend.app.domain.responses import ExecutionSummary, ResultItem

AlertStatus = Literal["open", "in_review", "escalated", "dismissed", "closed"]


class QueryRequest(ContractModel):
    """Query entry point: optional plan (Phase 4) or free-text routing (Phase 5)."""

    query: str = Field(min_length=1, max_length=2000)
    as_of: datetime
    filters: NormalizedFilters = Field(default_factory=NormalizedFilters)
    plan: ValidatedPlan | None = None
    route: RouteType = RouteType.FULL_INVESTIGATION
    detected_intent: IntentType | None = None

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("as_of must include a timezone")
        return value


class QueryResponse(ContractModel):
    request_id: str
    tool_results: list[ToolResult]
    answer: str = Field(min_length=1, max_length=10000)
    execution_summary: ExecutionSummary | None = None
    status: Literal["completed", "partial", "failed"] = "completed"
    parsed_intent: ParsedIntent | None = None
    route: RouteType | None = None
    clarification: str | None = None
    needs_planner: bool = False
    # Phase 9: FinalResponse fields so the UI matches the workflow aggregate exactly.
    results: list[ResultItem] = Field(default_factory=list, max_length=1000)
    charts: list[ChartSpec] = Field(default_factory=list, max_length=50)
    supporting_evidence: list[ToolResult] = Field(default_factory=list)


class InvestigationCreateRequest(ContractModel):
    query: str = Field(min_length=1, max_length=2000)
    as_of: datetime
    filters: NormalizedFilters = Field(default_factory=NormalizedFilters)
    plan: ValidatedPlan | None = None
    route: RouteType = RouteType.FULL_INVESTIGATION
    detected_intent: IntentType | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("as_of must include a timezone")
        return value


class InvestigationResponse(ContractModel):
    investigation_id: str
    request_id: str
    query_text: str
    route: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    execution_summary: ExecutionSummary | None = None
    answer: str | None = None
    parsed_intent: ParsedIntent | None = None
    clarification: str | None = None
    needs_planner: bool = False
    results: list[ResultItem] = Field(default_factory=list, max_length=1000)
    charts: list[ChartSpec] = Field(default_factory=list, max_length=50)
    supporting_evidence: list[ToolResult] = Field(default_factory=list)


class CustomerResponse(ContractModel):
    customer_id: str
    created_at: datetime
    status: str


class CustomerTransactionSummary(ContractModel):
    transaction_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    transaction_type: str


class CustomerDetailResponse(ContractModel):
    customer_id: str
    created_at: datetime
    status: str
    segment: str | None = None
    residence_country: str | None = None
    kyc_risk_rating: str | None = None
    recent_transactions: list[CustomerTransactionSummary] = Field(default_factory=list)


class CustomerListResponse(ContractModel):
    items: list[CustomerResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(ge=0)


class TransactionResponse(ContractModel):
    transaction_id: str
    customer_id: str
    account_id: str
    occurred_at: datetime
    amount_minor: int
    currency: str
    direction: str
    transaction_type: str
    channel: str
    country: str | None
    ml_eligible: bool
    ml_feature_ref: str | None
    data_source: str


class ScoreResponse(ContractModel):
    transaction_id: str
    status: Literal["scored", "skipped"]
    reason: str | None = None
    ml_score: float | None = Field(default=None, ge=0, le=1)
    is_flagged: bool | None = None
    threshold: float | None = Field(default=None, ge=0, le=1)
    model_version: str | None = None


class AlertCreateRequest(ContractModel):
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=128)
    investigation_id: str | None = None
    finding_code: str = Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    evidence_snapshot_ref: str = Field(min_length=1, max_length=128)
    policy_version: str = Field(min_length=1, max_length=64)
    investigation_window_start: datetime
    investigation_window_end: datetime
    request_id: str = Field(min_length=1, max_length=128)
    case_pack: dict[str, Any] | None = None

    @field_validator("investigation_window_start", "investigation_window_end")
    @classmethod
    def validate_window(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("investigation window bounds must include a timezone")
        return value


class AlertPatchRequest(ContractModel):
    status: AlertStatus
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    request_id: str = Field(min_length=1, max_length=128)
    evidence_version: str = Field(default="v1", min_length=1, max_length=64)


class AlertEventResponse(ContractModel):
    event_id: int
    alert_id: str
    timestamp: datetime
    from_status: str | None
    to_status: str
    reviewer_id: str
    reason: str
    request_id: str
    evidence_version: str
    risk_policy_version: str


class AlertResponse(ContractModel):
    alert_id: str
    investigation_id: str | None
    entity_type: str
    entity_id: str
    status: AlertStatus
    # Provisional Phase 3 placeholders derived from signal severity — not Phase 8 calibrated risk.
    risk_score: float
    risk_tier: RiskLevel
    escalation_action: EscalationAction
    evidence_snapshot_ref: str
    policy_version: str
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    history: list[AlertEventResponse] = Field(default_factory=list)
    case_pack: dict[str, Any] | None = None
