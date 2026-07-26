"""Shared runtime context passed to every Phase 3 tool handler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.domain.evidence import ToolResult
from backend.app.domain.filters import NormalizedFilters
from backend.app.policy.config import PolicyConfig


class FraudScorerProtocol(Protocol):
    def score_one(self, transaction: Any) -> Any: ...


@dataclass(slots=True)
class ToolContext:
    """Explicit inputs available to tool handlers."""

    session: Session
    policy: PolicyConfig
    settings: Settings
    filters: NormalizedFilters
    as_of: datetime
    scorer_factory: Callable[[], FraudScorerProtocol | None] | None = None
    prior_results: list[ToolResult] = field(default_factory=list)
    request_id: str | None = None
    investigation_id: str | None = None

    def get_scorer(self) -> FraudScorerProtocol | None:
        if self.scorer_factory is None:
            return None
        return self.scorer_factory()
