"""Time the six mandatory demo queries (local latency harness)."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.generation.orchestrator import generate_scenarios
from backend.app.generation.seeder import seed_runtime_bundle
from backend.app.main import create_app

AS_OF = datetime(2026, 7, 25, tzinfo=UTC)

QUERIES = [
    ("sql_only_amount", "Show me transactions over $10,000"),
    ("threshold_aggregation", "Which customers made 10+ transactions under $10,000?"),
    (
        "feature_only_spend",
        "Did customer cus-dev-42-spending-increase-00 suddenly increase spending this month?",
    ),
    (
        "structuring",
        "Find structuring patterns for customer cus-dev-42-structuring-00 in the last 30 days",
    ),
    ("entity_investigation", "Is customer ID cus-dev-42-structuring-00 suspicious?"),
    ("broad_eda", "Analyse this dataset for suspicious activity"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation/dev/latency_six_queries.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    work = Path("data/evaluation/dev/_latency_workdir")
    work.mkdir(parents=True, exist_ok=True)
    db = work / "latency.db"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_database_engine(url)
    Base.metadata.create_all(engine)
    result = generate_scenarios(
        seed=42,
        split="dev",
        generation_config_path=Path("config/generation/scenario_catalog.v1.yaml"),
        policy_config_path=Path("config/policy/reporting_thresholds.v1.yaml"),
    )
    with session_scope(session_factory(engine)) as session:
        seed_runtime_bundle(session, result.runtime, alembic_revision="head")
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "LatencyHarness",
            "database_url": url,
            "data_dir": work / "data",
            "chroma_persist_dir": work / "chroma",
            "policy_corpus_path": Path("config/policy/corpus/policy_excerpts.v1.json"),
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "risk_enabled": True,
            "explanation_enabled": True,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
            "risk_policy_path": Path("config/policy/risk_scoring.v1.yaml"),
        }
    )
    client = TestClient(create_app(settings))
    rows: list[dict[str, object]] = []
    for key, query in QUERIES:
        samples: list[float] = []
        last_invoked: list[str] = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            response = client.post(
                "/api/v1/query",
                json={"query": query, "as_of": AS_OF.isoformat()},
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            assert response.status_code == 200, response.text
            samples.append(elapsed_ms)
            last_invoked = list(response.json()["execution_summary"]["tools_invoked"])
        ordered = sorted(samples)
        p50 = statistics.median(ordered)
        # nearest-rank p95 for small n
        idx = min(len(ordered) - 1, max(0, round(0.95 * (len(ordered) - 1))))
        p95 = ordered[idx]
        rows.append(
            {
                "query_type": key,
                "query": query,
                "n": len(samples),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "mean_ms": round(statistics.fmean(samples), 2),
                "tools_invoked_last": last_invoked,
            }
        )
    payload = {
        "harness_version": "six_query_latency.v1",
        "seed": 42,
        "ollama_enabled": False,
        "machine_caveat": "Measured on the local developer machine; not a controlled bench.",
        "as_of": AS_OF.isoformat(),
        "results": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    engine.dispose()


if __name__ == "__main__":
    main()
