"""Prepare a local demo database (seed 42) and print run instructions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--split", choices=("dev", "ci_tiny"), default="dev")
    parser.add_argument("--skip-generate", action="store_true")
    parser.add_argument("--skip-migrate", action="store_true")
    return parser.parse_args()


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    args = parse_args()
    if not args.skip_migrate:
        run([sys.executable, "-m", "alembic", "upgrade", "head"])
    if not args.skip_generate:
        run(
            [
                sys.executable,
                "scripts/generate_aml_scenarios.py",
                "--seed",
                str(args.seed),
                "--split",
                args.split,
                "--verbose",
            ]
        )
    run(
        [
            sys.executable,
            "scripts/seed_database.py",
            "--seed",
            str(args.seed),
            "--split",
            args.split,
            "--verbose",
        ]
    )
    print(
        json.dumps(
            {
                "ok": True,
                "seed": args.seed,
                "split": args.split,
                "demo_as_of": "2026-07-25T00:00:00Z",
                "example_customers": [
                    "cus-dev-42-spending-increase-00",
                    "cus-dev-42-structuring-00",
                ],
                "next": [
                    "Set FRAUD_OLLAMA_ENABLED=false in .env (demo default)",
                    "uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000",
                    "cd frontend && npm install && npm run dev",
                    "Open http://127.0.0.1:5173 — health badge should be green",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
