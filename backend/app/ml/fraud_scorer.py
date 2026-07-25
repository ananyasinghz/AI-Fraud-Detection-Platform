"""Strict, versioned single and batch fraud-scoring API."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from pydantic import Field
from sklearn.pipeline import Pipeline

from backend.app.domain.base import ContractModel
from backend.app.ml.schema import RAW_FEATURES
from backend.app.ml.training import ArtifactMetadata


class FraudTransaction(ContractModel):
    Time: float = Field(ge=0)
    V1: float
    V2: float
    V3: float
    V4: float
    V5: float
    V6: float
    V7: float
    V8: float
    V9: float
    V10: float
    V11: float
    V12: float
    V13: float
    V14: float
    V15: float
    V16: float
    V17: float
    V18: float
    V19: float
    V20: float
    V21: float
    V22: float
    V23: float
    V24: float
    V25: float
    V26: float
    V27: float
    V28: float
    Amount: float = Field(ge=0)


class FraudScore(ContractModel):
    ml_score: float = Field(ge=0, le=1)
    is_flagged: bool
    threshold: float = Field(ge=0, le=1)
    model_version: str
    score_semantics: str = "ranking score; not a calibrated probability"


class FraudScorer:
    """Load one vetted artifact and apply its shared fitted preprocessor."""

    def __init__(self, pipeline: Pipeline, metadata: ArtifactMetadata) -> None:
        if metadata.raw_input_order != list(RAW_FEATURES):
            raise ValueError("artifact input schema does not match scorer schema")
        if tuple(pipeline.named_steps) != ("preprocessor", "classifier"):
            raise ValueError("artifact pipeline must contain preprocessor then classifier")
        self._pipeline = pipeline
        self.metadata = metadata

    @classmethod
    def from_artifact(cls, artifact_dir: Path) -> "FraudScorer":
        metadata = ArtifactMetadata.model_validate_json(
            (artifact_dir / "metadata.json").read_text(encoding="utf-8")
        )
        loaded: Any = joblib.load(artifact_dir / "model.joblib")
        if not isinstance(loaded, Pipeline):
            raise TypeError("model.joblib does not contain a scikit-learn Pipeline")
        return cls(loaded, metadata)

    @staticmethod
    def validate_ordered_mapping(values: Mapping[str, object]) -> FraudTransaction:
        if tuple(values.keys()) != RAW_FEATURES:
            raise ValueError(f"expected ordered fields {RAW_FEATURES}; got {tuple(values.keys())}")
        return FraudTransaction.model_validate(values)

    def score_one(self, transaction: FraudTransaction) -> FraudScore:
        return self.score_batch([transaction])[0]

    def score_batch(
        self,
        transactions: Sequence[FraudTransaction],
    ) -> list[FraudScore]:
        if not transactions:
            return []
        frame = pd.DataFrame(
            [transaction.model_dump() for transaction in transactions],
            columns=RAW_FEATURES,
        )
        scores = np.asarray(self._pipeline.predict_proba(frame)[:, 1], dtype=np.float64)
        threshold = self.metadata.threshold_selection.threshold
        return [
            FraudScore(
                ml_score=float(score),
                is_flagged=bool(score >= threshold),
                threshold=threshold,
                model_version=self.metadata.model_version,
            )
            for score in scores
        ]
