# Data Dictionary

**Status:** Phase 0 contract dictionary  
**Contract version:** `v1`

Phase 0 defines component-boundary schemas only. Database columns and feature definitions are added and versioned in Phases 1–2.

## Contract Conventions

- All timestamps must include a timezone and are normalized to UTC by execution code.
- Entity IDs are opaque strings, not database row numbers exposed for arithmetic.
- Currency codes use uppercase ISO-style three-character codes.
- Country codes use uppercase two-character codes.
- Monetary values entering filters use decimal values; database storage is selected in Phase 1.
- Unknown fields are rejected at contract boundaries.
- Risk scores use a `0..100` scale.
- Confidence uses a `0..1` scale and is not a risk score.
- `ml_score`, introduced later, is not called a calibrated probability without calibration evidence.

## AnalysisRequest

| Field | Type | Required | Notes |
|---|---|---:|---|
| `query` | string | yes | 1–2,000 characters |
| `as_of` | timezone-aware datetime | yes | Stable anchor for relative dates |
| `filters` | `NormalizedFilters` | no | Defaults to an explicitly empty scope |

## NormalizedFilters

| Field | Type | Constraints |
|---|---|---|
| `date_from`, `date_to` | datetime or null | timezone required; ordered |
| `customer_ids` | string list | unique; maximum 100 |
| `account_ids` | string list | unique; maximum 100 |
| `transaction_ids` | string list | unique; maximum 100 |
| `segment` | string or null | maximum 64 characters |
| `country` | string or null | uppercase two-character code |
| `transaction_type` | string or null | maximum 64 characters |
| `currency` | string or null | uppercase three-character code |
| `pattern_type` | enum or null | known AML pattern |
| `amount_min`, `amount_max` | decimal or null | non-negative and ordered |
| `max_results` | integer | 1–1,000; default 100 |

## ParsedIntent

Contains one allow-listed intent, target scope, normalized filters, parser confidence, extracted entities, ambiguities, and parser version.

## ValidatedPlan

A plan has 1–20 unique acyclic steps. Each step contains:

- unique `step_id`
- allow-listed `tool`
- validated operation name
- JSON-compatible parameters
- dependencies
- concise reason
- required/optional flag

Identical tool operations and dependency cycles are invalid.

## ToolResult

Every tool returns its tool/operation, status, exact scope, JSON-compatible data, evidence references, warnings, duration, timestamp, provenance, and optional safe error. Failed results require an error; skipped results require a reason.

## FinalResponse

The public response includes:

- contract and request identifiers
- generation timestamp
- execution summary
- informational and/or flagged results
- supporting tool evidence
- chart specifications
- human-readable answer

Informational results do not manufacture risk fields. Flagged results require an entity, risk score/level, confidence, reasons, escalation action, and evidence references.

## Future Database Entities

Phase 1 will define migrations and detailed fields for:

- customers and effective-dated customer profiles
- accounts
- transactions
- counterparties
- devices
- investigations
- alerts and append-only alert events

Those schemas must preserve the contract conventions above and update this document before use.
