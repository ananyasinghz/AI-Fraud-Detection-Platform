"""Validated dynamic-plan contracts."""

import json
from typing import Literal

from pydantic import Field, JsonValue, field_validator, model_validator

from backend.app.domain.base import ContractModel
from backend.app.domain.enums import ToolName


class PlanStep(ContractModel):
    """One allow-listed tool operation in a dynamic plan."""

    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    tool: ToolName
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(min_length=1, max_length=500)
    required: bool = True

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("depends_on cannot contain duplicates")
        return values


class ValidatedPlan(ContractModel):
    """A bounded, dependency-safe execution plan."""

    strategy: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    steps: list[PlanStep] = Field(min_length=1, max_length=20)
    priority: Literal["low", "normal", "high"] = "normal"
    planner_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_graph(self) -> "ValidatedPlan":
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step_id values must be unique")

        known = set(step_ids)
        signatures: set[tuple[str, str, str]] = set()
        graph: dict[str, list[str]] = {}
        for step in self.steps:
            if step.step_id in step.depends_on:
                raise ValueError(f"step '{step.step_id}' cannot depend on itself")
            unknown = set(step.depends_on) - known
            if unknown:
                names = ", ".join(sorted(unknown))
                raise ValueError(f"step '{step.step_id}' has unknown dependencies: {names}")
            signature = (
                step.tool.value,
                step.operation,
                json.dumps(step.parameters, sort_keys=True),
            )
            if signature in signatures:
                raise ValueError("plan cannot repeat an identical tool operation")
            signatures.add(signature)
            graph[step.step_id] = step.depends_on

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("plan dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in graph[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in step_ids:
            visit(step_id)
        return self
