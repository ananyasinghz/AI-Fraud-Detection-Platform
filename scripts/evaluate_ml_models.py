"""Run offline test evaluation for frozen ULB artifacts."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.ml.prepare import load_split_config
from backend.evaluation.ml_evaluation import evaluate_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split-config",
        type=Path,
        default=Path("config/ml/split.v1.yaml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    split_version = load_split_config(args.split_config).version
    result = evaluate_models(
        model_root=settings.model_dir / "ulb_v1",
        split_dir=settings.data_dir / "splits" / split_version,
        evaluation_dir=settings.data_dir / "evaluation" / "ml" / split_version,
        output_path=settings.data_dir / "evaluation" / "ml" / "test_metrics.v1.json",
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
