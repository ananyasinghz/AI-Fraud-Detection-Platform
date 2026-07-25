"""Seed one generated, label-free AML runtime bundle."""

import argparse
import json
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.generation.io import read_runtime_bundle
from backend.app.generation.seeder import seed_runtime_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int)
    parser.add_argument("--split", choices=("dev", "held_out", "ci_tiny"), default="dev")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    seed = args.seed
    if seed is None:
        seed = settings.heldout_seed if args.split == "held_out" else settings.development_seed
    bundle_path = args.bundle or (
        settings.data_dir / "generated" / args.split / f"seed-{seed}" / "runtime_bundle.json"
    )
    bundle = read_runtime_bundle(bundle_path)
    if bundle.seed != seed or bundle.split != args.split:
        raise ValueError("bundle seed/split does not match command arguments")
    if args.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "run_id": bundle.run_id,
                    "fingerprint": bundle.fingerprint,
                    "transactions": len(bundle.transactions),
                },
                indent=2 if args.verbose else None,
                sort_keys=True,
            )
        )
        return

    engine = create_database_engine(settings.database_url)
    factory = session_factory(engine)
    with session_scope(factory) as session:
        result = seed_runtime_bundle(session, bundle)
    engine.dispose()
    print(
        json.dumps(
            result.model_dump(mode="json"),
            indent=2 if args.verbose else None,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
