"""Analysis-request and parsed-intent contracts."""

from datetime import datetime

from pydantic import Field, field_validator

from backend.app.domain.base import ContractModel, is_timezone_aware
from backend.app.domain.enums import IntentType, TargetScope
from backend.app.domain.filters import NormalizedFilters


class AnalysisRequest(ContractModel):
    """Natural-language request entering the analysis boundary."""

    query: str = Field(min_length=1, max_length=2000)
    as_of: datetime
    filters: NormalizedFilters = Field(default_factory=NormalizedFilters)

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: datetime) -> datetime:
        if not is_timezone_aware(value):
            raise ValueError("as_of must include a timezone")
        return value


class ParsedIntent(ContractModel):
    """Validated interpretation produced by the NLU boundary."""

    intent: IntentType
    target_scope: TargetScope
    filters: NormalizedFilters
    confidence: float = Field(ge=0, le=1)
    extracted_entities: dict[str, list[str]] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list, max_length=20)
    parser_version: str = Field(min_length=1, max_length=64)
