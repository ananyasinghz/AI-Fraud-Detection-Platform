"""Prepare immutable, duplicate-group-safe ULB partitions."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.ml.prepare import load_split_config, prepare_ml_data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/ml/split.v1.yaml"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    config = load_split_config(args.config)
    result = prepare_ml_data(
        source_path=args.source or settings.raw_creditcard_path,
        raw_copy_path=settings.data_dir / "raw" / "creditcard.csv",
        split_dir=settings.data_dir / "splits" / config.version,
        evaluation_dir=settings.data_dir / "evaluation" / "ml" / config.version,
        config=config,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
