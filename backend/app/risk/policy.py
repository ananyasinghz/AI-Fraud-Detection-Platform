"""Load versioned risk-scoring policy for Phase 8."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class TierBounds(BaseModel):
    low_max_exclusive: float = 40
    medium_max_exclusive: float = 70


class CustomerRollupWeights(BaseModel):
    event_peak: float = 0.40
    pattern_breadth: float = 0.35
    profile_score: float = 0.20
    context_score: float = 0.05


class CustomerRollupConfig(BaseModel):
    version: str = "customer_rollup.v1"
    lookback_days: int = 90
    half_life_days: int = 90
    weights: CustomerRollupWeights = Field(default_factory=CustomerRollupWeights)
    rule_base_points: dict[str, float] = Field(
        default_factory=lambda: {"low": 10.0, "medium": 20.0, "high": 35.0, "critical": 50.0}
    )
    profile_score_cap: float = 100
    context_score_cap: float = 100
    context_cannot_force_suspicious: bool = True


class DataSufficiencyConfig(BaseModel):
    insufficient_penalty: float = 15
    insufficient_confidence_cap: float = 0.45
    full_confidence: float = 0.85
    reduced_confidence: float = 0.55


class RiskScoringPolicy(BaseModel):
    version: str
    disclaimer: str = ""
    tiers: TierBounds = Field(default_factory=TierBounds)
    severity_points: dict[str, float]
    signal_points: dict[str, float]
    data_sufficiency: DataSufficiencyConfig = Field(default_factory=DataSufficiencyConfig)
    customer_rollup: CustomerRollupConfig = Field(default_factory=CustomerRollupConfig)
    escalation: dict[str, str]
    ml_flag_threshold: float = 0.5


def load_risk_policy(path: Path) -> RiskScoringPolicy:
    payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("risk policy must be a YAML object")
    return RiskScoringPolicy.model_validate(payload)


@lru_cache(maxsize=4)
def get_risk_policy(path_str: str) -> RiskScoringPolicy:
    return load_risk_policy(Path(path_str))
