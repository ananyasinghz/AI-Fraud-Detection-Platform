"""Strict contracts for deterministic rule evaluation."""

from pydantic import Field, field_validator

from backend.app.domain.enums import EntityType, RuleSeverity, ValueType
from backend.app.domain.features import (
    FeatureValue,
    FrozenContractModel,
    Identifier,
    ScalarValue,
    Version,
)


class RuleThreshold(FeatureValue):
    """One typed policy threshold used by a rule."""

    value: ScalarValue


class RuleResult(FrozenContractModel):
    """Auditable result produced by one versioned rule."""

    rule_id: str = Field(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[A-Za-z0-9_-]+)+$",
    )
    version: Version
    fired: bool
    severity: RuleSeverity
    entity_type: EntityType
    entity_id: Identifier
    features_used: tuple[FeatureValue, ...]
    thresholds_used: tuple[RuleThreshold, ...]
    evidence_refs: tuple[Identifier, ...] = Field(default=(), max_length=100)
    reason_code: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    )

    @field_validator("features_used")
    @classmethod
    def validate_unique_features(
        cls,
        values: tuple[FeatureValue, ...],
    ) -> tuple[FeatureValue, ...]:
        if len(values) != len({value.name for value in values}):
            raise ValueError("features_used names cannot contain duplicates")
        return values

    @field_validator("thresholds_used")
    @classmethod
    def validate_unique_thresholds(
        cls,
        values: tuple[RuleThreshold, ...],
    ) -> tuple[RuleThreshold, ...]:
        if len(values) != len({value.name for value in values}):
            raise ValueError("thresholds_used names cannot contain duplicates")
        return values

    @field_validator("evidence_refs")
    @classmethod
    def validate_unique_evidence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("evidence_refs cannot contain duplicates")
        return values


__all__ = ["RuleResult", "RuleSeverity", "RuleThreshold", "ValueType"]
