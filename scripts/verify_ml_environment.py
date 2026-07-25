"""Reload the selected artifact and prove deterministic scorer behavior."""

import json

import pandas as pd

from backend.app.core.config import get_settings
from backend.app.ml.fraud_scorer import FraudScorer
from backend.app.ml.prepare import load_split_config


def main() -> None:
    settings = get_settings()
    split_version = load_split_config(settings.data_dir.parent / "config/ml/split.v1.yaml").version
    sample = pd.read_csv(
        settings.data_dir / "splits" / split_version / "test_features.csv.gz",
        nrows=1,
    ).to_dict(orient="records")[0]
    transaction = FraudScorer.validate_ordered_mapping(sample)
    scorer = FraudScorer.from_artifact(settings.ml_model_dir)
    first = scorer.score_one(transaction)
    second = scorer.score_one(transaction)
    batch = scorer.score_batch([transaction])[0]
    if first != second or first != batch:
        raise RuntimeError("repeated and batch/single scores differ")
    print(
        json.dumps(
            {
                "model_version": first.model_version,
                "first_ml_score": first.ml_score,
                "second_ml_score": second.ml_score,
                "batch_ml_score": batch.ml_score,
                "identical": True,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
