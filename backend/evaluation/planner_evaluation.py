"""Offline planner tool-selection metrics (not imported by app)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.domain.intent import AnalysisRequest
from backend.app.nlu.intent_parser import parse_intent
from backend.app.planning.planner import plan_for_intent

DEFAULT_FIXTURE = Path("backend/tests/fixtures/intent_queries.v1.json")


@dataclass
class PlannerScores:
    precision: float
    recall: float
    exact_tool_set: float
    n: int
    skipped_unlabeled: int


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("intent fixture must be a JSON object")
    return payload


def _tool_set(plan_tools: list[str]) -> set[str]:
    return set(plan_tools)


def evaluate_planner_fixture(
    path: Path = DEFAULT_FIXTURE,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Force planner+validator (fallback when Ollama off) against labeled tool sets."""
    payload = _load_fixture(path)
    as_of = datetime.fromisoformat(payload["as_of"])
    resolved = settings or Settings(
        environment="test",
        ollama_enabled=False,
        planner_enabled=False,
        development_seed=42,
        heldout_seed=99,
    )

    precision_num = 0.0
    recall_num = 0.0
    exact = 0
    labeled = 0
    skipped = 0
    failures: list[dict[str, Any]] = []

    for row in payload["queries"]:
        expected_invoked = row.get("tools_invoked")
        if expected_invoked is None:
            skipped += 1
            continue
        if row.get("expect_clarification"):
            skipped += 1
            continue

        labeled += 1
        request = AnalysisRequest(query=row["query"], as_of=as_of)
        parsed = parse_intent(request, settings=resolved)
        result = plan_for_intent(parsed, settings=resolved, force=True)
        if result.plan is None:
            failures.append(
                {
                    "id": row["id"],
                    "field": "plan",
                    "expected": expected_invoked,
                    "got": None,
                    "reasons": list(result.rejection_reasons),
                }
            )
            continue

        got = [step.tool.value for step in result.plan.steps]
        # Unique tool order as set for precision/recall.
        got_set = _tool_set(got)
        exp_set = _tool_set(list(expected_invoked))
        if not got_set and not exp_set:
            precision_num += 1.0
            recall_num += 1.0
            exact += 1
            continue
        if got_set == exp_set:
            exact += 1
        intersection = got_set & exp_set
        precision_num += len(intersection) / len(got_set) if got_set else 0.0
        recall_num += len(intersection) / len(exp_set) if exp_set else 0.0

        expected_skipped = set(row.get("tools_skipped") or [])
        if expected_skipped & got_set:
            failures.append(
                {
                    "id": row["id"],
                    "field": "tools_skipped_violated",
                    "expected_skipped": sorted(expected_skipped),
                    "got": sorted(got_set),
                }
            )

        if got_set != exp_set:
            failures.append(
                {
                    "id": row["id"],
                    "field": "tools_invoked",
                    "expected": sorted(exp_set),
                    "got": sorted(got_set),
                }
            )

    scores = PlannerScores(
        precision=(precision_num / labeled) if labeled else 1.0,
        recall=(recall_num / labeled) if labeled else 1.0,
        exact_tool_set=(exact / labeled) if labeled else 1.0,
        n=labeled,
        skipped_unlabeled=skipped,
    )
    return {
        "fixture": str(path),
        "scores": asdict(scores),
        "failures": failures[:50],
    }


def main() -> None:
    result = evaluate_planner_fixture()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
