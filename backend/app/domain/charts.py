"""Inspectable chart specification returned by analytical tools."""

from pydantic import Field, JsonValue

from backend.app.domain.base import ContractModel
from backend.app.domain.enums import ChartType


class ChartSpec(ContractModel):
    """Frontend-agnostic chart data with evidence lineage."""

    chart_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    chart_type: ChartType
    title: str = Field(min_length=1, max_length=200)
    data: dict[str, JsonValue]
    x_label: str | None = Field(default=None, max_length=100)
    y_label: str | None = Field(default=None, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list)
