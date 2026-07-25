"""Evidence and tool-result contracts."""

from datetime import datetime

from pydantic import Field, JsonValue, field_validator, model_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.filters import NormalizedFilters


class EvidenceReference(ContractModel):
    """Stable reference to one fact in a tool result."""

    evidence_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]+$",
    )
    tool: ToolName
    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    json_path: str = Field(min_length=1, max_length=256, pattern=r"^\$")
    label: str = Field(min_length=1, max_length=200)


class ToolProvenance(ContractModel):
    """Data and implementation lineage for a tool result."""

    source: str = Field(min_length=1, max_length=128)
    query_or_version: str = Field(min_length=1, max_length=128)
    dataset_version: str | None = Field(default=None, min_length=1, max_length=128)
    policy_version: str | None = Field(default=None, min_length=1, max_length=128)


class ToolError(ContractModel):
    """Safe failure details exposed across the workflow boundary."""

    code: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


class ToolResult(ContractModel):
    """Common envelope returned by every tool."""

    tool: ToolName
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    status: ToolStatus
    scope: NormalizedFilters
    data: dict[str, JsonValue] = Field(default_factory=dict)
    evidence: list[EvidenceReference] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    duration_ms: int = Field(ge=0)
    produced_at: datetime
    provenance: ToolProvenance
    error: ToolError | None = None

    @field_validator("produced_at")
    @classmethod
    def validate_produced_at(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("produced_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_status_payload(self) -> "ToolResult":
        if self.status is ToolStatus.FAILED and self.error is None:
            raise ValueError("failed tool results require error details")
        if self.status is not ToolStatus.FAILED and self.error is not None:
            raise ValueError("only failed tool results may contain an error")
        if self.status is ToolStatus.SKIPPED and not self.warnings:
            raise ValueError("skipped tool results require a reason in warnings")
        return self
