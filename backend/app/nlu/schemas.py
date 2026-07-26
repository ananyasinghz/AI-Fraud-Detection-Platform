"""Internal LLM draft schema before date normalization and validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field

from backend.app.domain.base import ContractModel
from backend.app.domain.enums import IntentType, PatternType, TargetScope


class IntentDraft(ContractModel):
    """Loose structured extraction produced by Ollama or the fallback extractor."""

    intent: IntentType
    target_scope: TargetScope = TargetScope.DATASET
    confidence: float = Field(ge=0, le=1, default=0.5)
    customer_ids: list[str] = Field(default_factory=list)
    account_ids: list[str] = Field(default_factory=list)
    transaction_ids: list[str] = Field(default_factory=list)
    segment: str | None = None
    country: str | None = None
    transaction_type: str | None = None
    currency: str | None = None
    pattern_type: PatternType | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None
    max_results: int | None = Field(default=None, ge=1, le=1000)
    relative_date: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    ambiguities: list[str] = Field(default_factory=list)
