"""Execution-summary and final-response contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.charts import ChartSpec
from backend.app.domain.enums import (
    EntityType,
    EscalationAction,
    IntentType,
    RiskLevel,
    RouteType,
    ToolName,
)
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import ValidatedPlan


class SkippedTool(ContractModel):
    """One tool omitted from execution with an inspectable reason."""

    tool: ToolName
    reason: str = Field(min_length=1, max_length=500)


class ExecutionSummary(ContractModel):
    """Trace-derived account of what the agent understood and executed."""

    query: str = Field(min_length=1, max_length=2000)
    detected_intent: IntentType
    route: RouteType
    filters: NormalizedFilters
    plan: ValidatedPlan | None = None
    tools_invoked: list[ToolName] = Field(default_factory=list)
    tools_skipped: list[SkippedTool] = Field(default_factory=list)
    fallbacks: list[str] = Field(default_factory=list, max_length=20)
    warnings: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_tool_sets(self) -> "ExecutionSummary":
        invoked = self.tools_invoked
        if len(invoked) != len(set(invoked)):
            raise ValueError("tools_invoked cannot contain duplicates")
        skipped = [item.tool for item in self.tools_skipped]
        if len(skipped) != len(set(skipped)):
            raise ValueError("tools_skipped cannot contain duplicates")
        overlap = set(invoked) & set(skipped)
        if overlap:
            names = ", ".join(sorted(tool.value for tool in overlap))
            raise ValueError(f"tools cannot be both invoked and skipped: {names}")
        return self


class InformationalResult(ContractModel):
    """A direct SQL/feature answer that does not manufacture risk."""

    result_type: Literal["informational"] = "informational"
    entity_type: EntityType | None = None
    entity_id: str | None = Field(default=None, min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=1000)
    data: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class FlaggedResult(ContractModel):
    """A suspicious finding with complete risk and escalation fields."""

    result_type: Literal["flagged"] = "flagged"
    entity_type: EntityType
    entity_id: str = Field(min_length=1, max_length=128)
    risk_score: float = Field(ge=0, le=100)
    risk_level: RiskLevel
    confidence: float = Field(ge=0, le=1)
    reasons: list[str] = Field(min_length=1, max_length=20)
    escalation_action: EscalationAction
    evidence_refs: list[str] = Field(min_length=1, max_length=100)

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_refs cannot contain duplicates")
        return values


ResultItem = Annotated[InformationalResult | FlaggedResult, Field(discriminator="result_type")]


class FinalResponse(ContractModel):
    """Versioned public response returned by investigations."""

    contract_version: Literal["v1"] = "v1"
    request_id: str = Field(min_length=1, max_length=128)
    generated_at: datetime
    execution_summary: ExecutionSummary
    results: list[ResultItem] = Field(default_factory=list, max_length=1000)
    supporting_evidence: list[ToolResult] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list, max_length=50)
    answer: str = Field(min_length=1, max_length=10000)

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("generated_at must include a timezone")
        return value
