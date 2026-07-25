"""Train first-party ULB fraud-scoring models."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.ml.prepare import load_split_config
from backend.app.ml.training import load_training_config, train_models


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split-config",
        type=Path,
        default=Path("config/ml/split.v1.yaml"),
    )
    parser.add_argument(
        "--training-config",
        type=Path,
        default=Path("config/ml/training.v1.yaml"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    split_version = load_split_config(args.split_config).version
    result = train_models(
        split_dir=settings.data_dir / "splits" / split_version,
        model_root=settings.model_dir / "ulb_v1",
        config=load_training_config(args.training_config),
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
