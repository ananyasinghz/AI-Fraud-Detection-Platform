"""Transaction scoring service with lazy FraudScorer loading."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.data.repositories import TransactionRepository
from backend.app.domain.api import ScoreResponse
from backend.app.services.feature_ref import features_as_mapping, load_ulb_features
from backend.app.tools.context import FraudScorerProtocol


class _ScorerCache:
    loaded: bool = False
    scorer: FraudScorerProtocol | None = None


def build_scorer_factory(settings: Settings) -> Callable[[], FraudScorerProtocol | None]:
    """Return a lazy factory that never imports ML until first successful load."""
    cache = _ScorerCache()

    def factory() -> FraudScorerProtocol | None:
        if cache.loaded:
            return cache.scorer
        cache.loaded = True
        if not settings.ml_enabled:
            return None
        artifact_dir = Path(settings.ml_model_dir)
        if not (artifact_dir / "model.joblib").is_file():
            return None
        from backend.app.ml.fraud_scorer import FraudScorer

        cache.scorer = FraudScorer.from_artifact(artifact_dir)
        return cache.scorer

    return factory


def score_transaction(
    session: Session,
    transaction_id: str,
    *,
    scorer_factory: Callable[[], FraudScorerProtocol | None],
) -> ScoreResponse:
    transaction = TransactionRepository(session).get_by_id(transaction_id)
    if transaction is None:
        raise AppError(
            code="TRANSACTION_NOT_FOUND",
            message="transaction not found",
            status_code=404,
        )
    if not transaction.ml_eligible or not transaction.ml_feature_ref:
        return ScoreResponse(
            transaction_id=transaction_id,
            status="skipped",
            reason="ML_INELIGIBLE",
        )

    scorer = scorer_factory()
    if scorer is None:
        return ScoreResponse(
            transaction_id=transaction_id,
            status="skipped",
            reason="SCORER_UNAVAILABLE",
        )

    try:
        features = load_ulb_features(transaction.ml_feature_ref)
        from backend.app.ml.fraud_scorer import FraudScorer

        ordered = FraudScorer.validate_ordered_mapping(features_as_mapping(features))
        score: Any = scorer.score_one(ordered)
    except Exception:
        return ScoreResponse(
            transaction_id=transaction_id,
            status="skipped",
            reason="FEATURES_UNAVAILABLE",
        )

    return ScoreResponse(
        transaction_id=transaction_id,
        status="scored",
        ml_score=float(score.ml_score),
        is_flagged=bool(score.is_flagged),
        threshold=float(score.threshold),
        model_version=str(score.model_version),
    )
