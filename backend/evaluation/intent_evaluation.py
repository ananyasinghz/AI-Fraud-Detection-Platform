"""Offline intent/router metrics on labeled NL queries (not imported by app)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.domain.intent import AnalysisRequest
from backend.app.nlu.intent_parser import parse_intent
from backend.app.nlu.router import route_parsed_intent

DEFAULT_FIXTURE = Path("backend/tests/fixtures/intent_queries.v1.json")


@dataclass
class FieldScores:
    intent: float
    entity_ids: float
    dates: float
    pattern_type: float
    transaction_type: float
    route: float
    n: int


def _load_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("intent fixture must be a JSON object")
    return payload


def evaluate_intent_fixture(
    path: Path = DEFAULT_FIXTURE,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    payload = _load_fixture(path)
    as_of = datetime.fromisoformat(payload["as_of"])
    resolved_settings = settings or Settings(
        environment="test",
        ollama_enabled=False,
        development_seed=42,
        heldout_seed=99,
    )
    totals = {
        "intent": 0,
        "entity_ids": 0,
        "dates": 0,
        "pattern_type": 0,
        "transaction_type": 0,
        "route": 0,
    }
    denom = {
        "intent": 0,
        "entity_ids": 0,
        "dates": 0,
        "pattern_type": 0,
        "transaction_type": 0,
        "route": 0,
    }
    failures: list[dict[str, Any]] = []

    for row in payload["queries"]:
        request = AnalysisRequest(query=row["query"], as_of=as_of)
        parsed = parse_intent(request, settings=resolved_settings)
        decision = route_parsed_intent(
            parsed,
            confidence_floor=resolved_settings.intent_confidence_floor,
        )

        denom["intent"] += 1
        if parsed.intent.value == row["expected_intent"]:
            totals["intent"] += 1
        else:
            failures.append(
                {
                    "id": row["id"],
                    "field": "intent",
                    "expected": row["expected_intent"],
                    "got": parsed.intent.value,
                }
            )

        if "expected_customer_ids" in row:
            denom["entity_ids"] += 1
            expected = list(row["expected_customer_ids"])
            got = list(parsed.filters.customer_ids)
            if got == expected:
                totals["entity_ids"] += 1
            else:
                failures.append(
                    {
                        "id": row["id"],
                        "field": "entity_ids",
                        "expected": expected,
                        "got": got,
                    }
                )

        if "expect_relative_date" in row:
            denom["dates"] += 1
            # Date normalizer must produce a bounded window when relative expected.
            ok = parsed.filters.date_from is not None and parsed.filters.date_to is not None
            if ok:
                totals["dates"] += 1
            else:
                failures.append({"id": row["id"], "field": "dates", "expected": "window"})

        if "expected_pattern_type" in row:
            denom["pattern_type"] += 1
            got_pattern = parsed.filters.pattern_type.value if parsed.filters.pattern_type else None
            if got_pattern == row["expected_pattern_type"]:
                totals["pattern_type"] += 1
            else:
                failures.append(
                    {
                        "id": row["id"],
                        "field": "pattern_type",
                        "expected": row["expected_pattern_type"],
                        "got": got_pattern,
                    }
                )

        if "expected_transaction_type" in row:
            denom["transaction_type"] += 1
            if parsed.filters.transaction_type == row["expected_transaction_type"]:
                totals["transaction_type"] += 1

        if "expected_route" in row:
            denom["route"] += 1
            if decision.route.value == row["expected_route"]:
                totals["route"] += 1
            else:
                failures.append(
                    {
                        "id": row["id"],
                        "field": "route",
                        "expected": row["expected_route"],
                        "got": decision.route.value,
                    }
                )

        if row.get("expected_amount_min") is not None:
            expected_min = Decimal(str(row["expected_amount_min"]))
            if parsed.filters.amount_min != expected_min:
                failures.append(
                    {
                        "id": row["id"],
                        "field": "amount_min",
                        "expected": str(expected_min),
                        "got": str(parsed.filters.amount_min),
                    }
                )

        if (
            row.get("expect_clarification")
            and decision.plan is not None
            and not decision.clarification
        ):
            # Clarification cases may still template in some paths; count soft fail.
            failures.append(
                {
                    "id": row["id"],
                    "field": "clarification",
                    "expected": True,
                    "got": False,
                }
            )

    def ratio(key: str) -> float:
        if denom[key] == 0:
            return 1.0
        return totals[key] / denom[key]

    scores = FieldScores(
        intent=ratio("intent"),
        entity_ids=ratio("entity_ids"),
        dates=ratio("dates"),
        pattern_type=ratio("pattern_type"),
        transaction_type=ratio("transaction_type"),
        route=ratio("route"),
        n=len(payload["queries"]),
    )
    return {
        "fixture": str(path),
        "scores": asdict(scores),
        "denominators": denom,
        "failures": failures[:50],
    }


def main() -> None:
    result = evaluate_intent_fixture()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
