"""Helpers for building ToolResult envelopes."""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from backend.app.domain.enums import ToolName, ToolStatus
from backend.app.domain.evidence import (
    EvidenceReference,
    ToolError,
    ToolProvenance,
    ToolResult,
)
from backend.app.domain.filters import NormalizedFilters


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def make_result(
    *,
    tool: ToolName,
    operation: str,
    status: ToolStatus,
    scope: NormalizedFilters,
    data: dict[str, Any] | None = None,
    evidence: list[EvidenceReference] | None = None,
    warnings: list[str] | None = None,
    duration_ms: int,
    provenance: ToolProvenance,
    error: ToolError | None = None,
) -> ToolResult:
    return ToolResult(
        tool=tool,
        operation=operation,
        status=status,
        scope=scope,
        data=data or {},
        evidence=evidence or [],
        warnings=warnings or [],
        duration_ms=duration_ms,
        produced_at=utc_now(),
        provenance=provenance,
        error=error,
    )


class Timer:
    """Simple wall-clock timer for tool duration_ms."""

    def __init__(self) -> None:
        self._start = perf_counter()

    def ms(self) -> int:
        return max(0, int((perf_counter() - self._start) * 1000))
