"""Smoke the six demo chip queries against a live API."""

from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1/query"
AS_OF = "2026-07-25T00:00:00Z"
QUERIES = [
    "Show me transactions over $5,000",
    "Which customers made 10+ transactions under $10,000?",
    "Find structuring patterns for customer cus-dev-42-structuring-00 in the last 30 days",
    "Is customer ID cus-dev-42-structuring-00 suspicious?",
    "Did customer cus-dev-42-spending-increase-00 suddenly increase spending this month?",
    "Analyse this dataset for suspicious activity",
]


def main() -> int:
    failed = 0
    for query in QUERIES:
        t0 = time.time()
        request = urllib.request.Request(
            BASE,
            data=json.dumps({"query": query, "as_of": AS_OF, "filters": {}}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=240) as resp:
                data = json.loads(resp.read().decode())
            summary = data.get("execution_summary") or {}
            status = data.get("status")
            ok = status in {"completed", "partial", "needs_clarification"}
            if not ok:
                failed += 1
            print(
                ("PASS" if ok else "FAIL"),
                f"{time.time() - t0:.1f}s",
                "|",
                status,
                "|",
                summary.get("detected_intent"),
                "|",
                summary.get("route"),
                "|",
                summary.get("tools_invoked"),
                "|",
                query[:72],
                flush=True,
            )
            warnings = summary.get("warnings") or []
            if warnings:
                print("   warnings:", warnings[:3], flush=True)
        except Exception as exc:
            failed += 1
            print("FAIL", f"{time.time() - t0:.1f}s", "|", exc, "|", query[:72], flush=True)
    print(f"\nSUMMARY: {len(QUERIES) - failed}/{len(QUERIES)} query pipelines ok", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
