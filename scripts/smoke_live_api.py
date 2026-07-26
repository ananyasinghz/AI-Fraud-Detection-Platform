"""Live smoke checks for /api/v1 endpoints and demo query pipelines."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime

BASE = "http://127.0.0.1:8000/api/v1"
AS_OF = "2026-07-25T00:00:00Z"
results: list[bool] = []


def req(method: str, path: str, body: dict | None = None, timeout: float = 240.0):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode()
            elapsed = time.time() - t0
            return resp.status, json.loads(raw) if raw else {}, elapsed, None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        elapsed = time.time() - t0
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:500]}
        return exc.code, payload, elapsed, str(exc)
    except Exception as exc:
        return None, {}, time.time() - t0, str(exc)


def check(name: str, ok: bool, detail: str, elapsed: float | None = None) -> None:
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if elapsed is not None:
        line += f" ({elapsed:.1f}s)"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    results.append(ok)


def main() -> int:
    code, body, elapsed, _err = req("GET", "/health", timeout=10)
    check(
        "GET /health",
        code == 200 and body.get("status") == "ok",
        f"status={code} env={body.get('environment')}",
        elapsed,
    )

    code, body, elapsed, _err = req("GET", "/customers?limit=20&offset=0", timeout=30)
    items = body.get("items") or []
    cust_id = items[0]["customer_id"] if items else None
    check(
        "GET /customers",
        code == 200 and len(items) > 0,
        f"status={code} total={body.get('total')} sample={cust_id}",
        elapsed,
    )

    if cust_id:
        code, body, elapsed, _err = req(
            "GET",
            f"/customers/{urllib.parse.quote(cust_id)}",
            timeout=30,
        )
        txs = body.get("recent_transactions") or []
        check(
            "GET /customers/{id}",
            code == 200 and body.get("customer_id") == cust_id,
            (
                f"status={code} segment={body.get('segment')} "
                f"country={body.get('residence_country')} txs={len(txs)}"
            ),
            elapsed,
        )
    else:
        check("GET /customers/{id}", False, "no customer id from list")

    code, body, elapsed, _err = req("GET", "/alerts?limit=50&offset=0", timeout=30)
    check(
        "GET /alerts",
        code == 200,
        f"status={code} total={body.get('total')} items={len(body.get('items') or [])}",
        elapsed,
    )

    unique = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    entity = cust_id or "cus-smoke"
    pack = {
        "pack_version": "alert_case_pack.v1",
        "query": f"smoke {unique}",
        "request_id": f"smoke-{unique}",
        "explanation": {"summary": "smoke pack", "source": "template", "reasons": ["smoke"]},
        "supporting_evidence": [],
    }
    payload = {
        "entity_type": "customer",
        "entity_id": entity,
        "finding_code": "UI_MANUAL_ALERT",
        "severity": "medium",
        "evidence_snapshot_ref": f"ui:{entity}"[:128],
        "policy_version": "risk_scoring.v1",
        "investigation_window_start": "2026-04-26T00:00:00Z",
        "investigation_window_end": AS_OF,
        "request_id": f"smoke-create-{unique}",
        "case_pack": pack,
    }
    code, body, elapsed, _err = req("POST", "/alerts", payload, timeout=30)
    alert_id = body.get("alert_id")
    ref_ok = str(body.get("evidence_snapshot_ref") or "").startswith("pack:")
    pack_ok = isinstance(body.get("case_pack"), dict)
    check(
        "POST /alerts + case_pack",
        code == 200 and bool(alert_id) and ref_ok and pack_ok,
        f"status={code} id={alert_id} ref={body.get('evidence_snapshot_ref')}",
        elapsed,
    )

    if alert_id:
        code, body, elapsed, _err = req("GET", f"/alerts/{alert_id}", timeout=30)
        check(
            "GET /alerts/{id}",
            code == 200 and (body.get("case_pack") or {}).get("query") == pack["query"],
            f"status={code} pack_query={(body.get('case_pack') or {}).get('query')}",
            elapsed,
        )
        code, body, elapsed, _err = req(
            "PATCH",
            f"/alerts/{alert_id}",
            {
                "status": "in_review",
                "reviewer_id": "smoke_reviewer",
                "reason": "smoke acknowledge",
                "request_id": f"smoke-patch-{unique}",
            },
            timeout=30,
        )
        check(
            "PATCH /alerts/{id} -> in_review",
            code == 200 and body.get("status") == "in_review",
            f"status={code} alert_status={body.get('status')}",
            elapsed,
        )
    else:
        check("GET /alerts/{id}", False, "no alert_id")
        check("PATCH /alerts/{id}", False, "no alert_id")

    tx_id = None
    if cust_id:
        code, body, elapsed, _err = req(
            "GET",
            f"/customers/{urllib.parse.quote(cust_id)}",
            timeout=30,
        )
        txs = body.get("recent_transactions") or []
        if txs:
            tx_id = txs[0]["transaction_id"]

    if tx_id:
        code, body, elapsed, _err = req(
            "GET",
            f"/transactions/{urllib.parse.quote(tx_id)}",
            timeout=30,
        )
        check(
            "GET /transactions/{id}",
            code == 200 and body.get("transaction_id") == tx_id,
            f"status={code} amount_minor={body.get('amount_minor')}",
            elapsed,
        )
        code, body, elapsed, _err = req(
            "POST",
            f"/transactions/{urllib.parse.quote(tx_id)}/score",
            timeout=60,
        )
        check(
            "POST /transactions/{id}/score",
            code == 200 and body.get("status") in ("scored", "skipped"),
            f"status={code} score_status={body.get('status')} reason={body.get('reason')}",
            elapsed,
        )
    else:
        check("GET /transactions/{id}", False, "no transaction on sample customer")
        check("POST /transactions/{id}/score", False, "skipped — no tx")

    code, body, elapsed, _err = req(
        "POST",
        "/investigations",
        {"query": "Show me transactions over $5000", "as_of": AS_OF, "filters": {}},
        timeout=240,
    )
    inv_id = body.get("investigation_id")
    check(
        "POST /investigations",
        code == 200 and bool(inv_id),
        f"status={code} id={inv_id} keys={list(body.keys())[:8]}",
        elapsed,
    )
    if inv_id:
        code2, _body2, elapsed2, _err2 = req("GET", f"/investigations/{inv_id}", timeout=30)
        check("GET /investigations/{id}", code2 == 200, f"status={code2}", elapsed2)
    else:
        check("GET /investigations/{id}", False, "investigation_id missing")

    print("--- query pipelines (live DB; Ollama may be slow) ---", flush=True)
    queries = [
        ("SQL over $5k", "Show me transactions over $5000"),
        ("Threshold check", "Did any customer exceed cash reporting thresholds last month?"),
        ("Structuring scoped", "Is there structuring activity for customer cus-dev-42-0001?"),
    ]
    for label, query in queries:
        code, body, elapsed, err = req(
            "POST",
            "/query",
            {"query": query, "as_of": AS_OF, "filters": {}},
            timeout=240,
        )
        if code != 200:
            check(
                f"POST /query [{label}]",
                False,
                f"status={code} err={err} body={str(body)[:200]}",
                elapsed,
            )
            continue
        summary = body.get("execution_summary") or {}
        tools = summary.get("tools_invoked") or []
        status = body.get("status")
        sql_count = 0
        evidence = body.get("supporting_evidence") or body.get("tool_results") or []
        for tool_result in evidence:
            if tool_result.get("tool") != "sql_lookup":
                continue
            data = tool_result.get("data") or {}
            if isinstance(data.get("count"), int):
                sql_count = max(sql_count, data["count"])
            txs = data.get("transactions") or []
            if txs:
                sql_count = max(sql_count, len(txs))
        flagged = [r for r in (body.get("results") or []) if r.get("result_type") == "flagged"]
        expl = None
        for tool_result in evidence:
            if tool_result.get("tool") == "explanation" and tool_result.get("status") == "success":
                expl = (tool_result.get("data") or {}).get("source")
        detail = (
            f"status={status} intent={summary.get('detected_intent')} tools={tools} "
            f"sql_rows~={sql_count} flagged={len(flagged)} expl_source={expl} "
            f"charts={len(body.get('charts') or [])}"
        )
        ok = status in ("completed", "partial", "needs_clarification") and bool(summary)
        check(f"POST /query [{label}]", ok, detail, elapsed)

    failed = sum(1 for item in results if not item)
    print(f"\nSUMMARY: {len(results) - failed}/{len(results)} checks passed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
