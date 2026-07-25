# Contract v1 Examples

These examples are illustrative JSON payloads for the strict Pydantic models in `backend/app/domain/`.

## Analysis Request

```json
{
  "query": "Find structuring patterns in the last 30 days",
  "as_of": "2026-07-25T12:00:00Z",
  "filters": {
    "date_from": "2026-06-25T12:00:00Z",
    "date_to": "2026-07-25T12:00:00Z",
    "customer_ids": [],
    "account_ids": [],
    "transaction_ids": [],
    "segment": null,
    "country": null,
    "transaction_type": null,
    "currency": "USD",
    "pattern_type": "structuring",
    "amount_min": null,
    "amount_max": null,
    "max_results": 100
  }
}
```

## Validated Plan

```json
{
  "strategy": "targeted_pattern_search",
  "priority": "normal",
  "planner_version": "template.v1",
  "steps": [
    {
      "step_id": "features",
      "tool": "feature_engineering",
      "operation": "structuring_features",
      "parameters": {
        "window_days": 30
      },
      "depends_on": [],
      "reason": "Compute only features required for structuring",
      "required": true
    },
    {
      "step_id": "rules",
      "tool": "anomaly_detection",
      "operation": "rules_only",
      "parameters": {},
      "depends_on": [
        "features"
      ],
      "reason": "Apply structuring rules without unrelated ML",
      "required": true
    }
  ]
}
```

## Informational Final Response

```json
{
  "contract_version": "v1",
  "request_id": "req-demo-1",
  "generated_at": "2026-07-25T12:00:01Z",
  "execution_summary": {
    "query": "Show transactions over $10,000",
    "detected_intent": "simple_lookup",
    "route": "simple_lookup",
    "filters": {
      "date_from": null,
      "date_to": null,
      "customer_ids": [],
      "account_ids": [],
      "transaction_ids": [],
      "segment": null,
      "country": null,
      "transaction_type": null,
      "currency": "USD",
      "pattern_type": null,
      "amount_min": "10000",
      "amount_max": null,
      "max_results": 100
    },
    "plan": null,
    "tools_invoked": [
      "sql_lookup"
    ],
    "tools_skipped": [
      {
        "tool": "eda",
        "reason": "A direct amount filter does not require dataset profiling"
      }
    ],
    "fallbacks": [],
    "warnings": []
  },
  "results": [
    {
      "result_type": "informational",
      "entity_type": null,
      "entity_id": null,
      "summary": "Three transactions matched",
      "data": {
        "count": 3
      },
      "evidence_refs": [
        "ev.sql.1"
      ]
    }
  ],
  "supporting_evidence": [],
  "charts": [],
  "answer": "Three transactions matched the requested amount filter."
}
```

Informational responses intentionally omit risk and escalation fields. A flagged result cannot validate without risk, reasons, escalation, and at least one evidence reference.
