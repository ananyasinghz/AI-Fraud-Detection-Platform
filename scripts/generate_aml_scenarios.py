"""Generate deterministic AML runtime data and an isolated evaluation manifest."""

import argparse
import json

from backend.app.core.config import get_settings
from backend.app.generation import generate_scenarios
from backend.app.generation.io import write_runtime_bundle
from backend.evaluation.scenario_manifest import build_manifest, write_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int)
    parser.add_argument("--split", choices=("dev", "held_out", "ci_tiny"), default="dev")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    seed = args.seed
    if seed is None:
        seed = settings.heldout_seed if args.split == "held_out" else settings.development_seed
    result = generate_scenarios(
        seed=seed,
        split=args.split,
        generation_config_path=settings.scenario_config_path,
        policy_config_path=settings.policy_config_path,
    )
    output_dir = settings.data_dir / "generated" / args.split / f"seed-{seed}"
    runtime_path = output_dir / "runtime_bundle.json"
    manifest_path = settings.data_dir / "evaluation" / args.split / f"seed-{seed}.json"
    if not args.dry_run:
        write_runtime_bundle(result.runtime, runtime_path)
        write_manifest(build_manifest(result), manifest_path)

    summary = {
        "dry_run": args.dry_run,
        "run_id": result.runtime.run_id,
        "fingerprint": result.runtime.fingerprint,
        "customers": len(result.runtime.customers),
        "transactions": len(result.runtime.transactions),
        "scenarios": len(result.annotations),
        "runtime_path": str(runtime_path),
        "manifest_path": str(manifest_path),
    }
    print(json.dumps(summary, indent=2 if args.verbose else None, sort_keys=True))


if __name__ == "__main__":
    main()
