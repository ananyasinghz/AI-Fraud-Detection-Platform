# Data Dictionary

**Status:** Phase 1 implemented  
**Contract version:** `v1`

This document covers the frozen Phase 0 boundary contracts and the Phase 1 relational and ULB ML schemas.

## Contract Conventions

- All timestamps must include a timezone and are normalized to UTC by execution code.
- Entity IDs are opaque strings, not database row numbers exposed for arithmetic.
- Currency codes use uppercase ISO-style three-character codes.
- Country codes use uppercase two-character codes.
- Monetary values entering filters use decimal values. Database money is stored as integer minor units with a separate currency code.
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

## ExecutionSummary

Records the original query, detected intent, explicit route (`simple_lookup`, `feature_only`, or `full_investigation`), normalized filters, optional validated plan, tools invoked, tools skipped with reasons, fallbacks, and warnings. It is sourced from the eventual execution trace rather than reconstructed by an LLM.

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

## Relational Storage

Schema revision `0001` is managed by Alembic. SQLite foreign keys are enabled on every connection.

### `dataset_runs`

One immutable provenance record per seeded dataset.

| Field | Type | Notes |
|---|---|---|
| `run_id` | string PK | Stable idempotency key |
| `run_kind` | string | `aml_seed` or `ml_prepare` |
| `generator_version` | string/null | Scenario generator version |
| `alembic_revision` | string | Schema revision used while seeding |
| `random_seed` | integer/null | Generation/split seed |
| `split_name` | string/null | `dev`, `held_out`, or fixture split |
| `source_fingerprint` | string/null | SHA256/runtime-bundle fingerprint |
| `record_counts` | JSON | Counts by entity/table |
| `created_at` | UTC datetime | Deterministic generation instant |

### `customers`

`customer_id` is the opaque primary key. `created_at` is UTC. `status` is constrained to `active`, `inactive`, or `closed`.

### `customer_profiles`

Profiles are effective-dated half-open intervals: `profile_effective_from <= as_of < profile_effective_to`; null `profile_effective_to` means current. Application writes reject interval overlap.

| Field | Type | Notes |
|---|---|---|
| `profile_id` | integer PK | Internal row identity |
| `customer_id` | FK | Cascades with customer deletion |
| `segment` | string | `retail`, `sme`, or `corporate` |
| `residence_country` | char(2) | Uppercase ISO-style code |
| `occupation_or_industry` | string/null | Declared context |
| `declared_annual_income_minor` | integer/null | Retail income; never inferred from a band |
| `declared_revenue_band` | string/null | SME/corporate declaration; no numeric midpoint |
| `income_currency` | char(3)/null | Currency for declared income |
| `expected_monthly_volume_min_minor` | integer/null | Non-negative profile lower bound |
| `expected_monthly_volume_max_minor` | integer/null | Greater than/equal to lower bound |
| `volume_currency` | char(3)/null | Currency for volume range |
| `kyc_risk_rating` | string/null | `low`, `medium`, or `high` |
| `pep_flag` | boolean | Context only; not a standalone decision |
| `profile_effective_from/to` | UTC datetime | Non-overlapping validity interval |
| `profile_source` | string | Profile provenance |

Missing declarations remain null and are returned as explicit profile-resolution warnings; they are not replaced with zero.

Index: `ix_profile_customer_effective(customer_id, profile_effective_from)`.

### `accounts`

`account_id` is the primary key; `customer_id` is a foreign key. `opened_at` is the canonical source for account tenure. Other fields are `account_type`, `currency`, optional `country`, and constrained `status`.

Index: `ix_accounts_customer(customer_id)`.

### `counterparties` and `devices`

Counterparties hold an opaque id, display name, optional country, and kind. Devices hold id/type plus UTC `first_seen_at` and `last_seen_at`; the end cannot precede the start.

### `transactions`

| Field | Type | Notes |
|---|---|---|
| `transaction_id` | string PK | Stable source identity |
| `account_id`, `customer_id` | FK | Entity scope |
| `occurred_at`, `posted_at` | UTC datetime | Posted time may be null |
| `amount_minor` | integer | Non-negative; generated directly as an integer |
| `currency` | char(3) | No currency conversion is implied |
| `direction` | string | `credit` or `debit` |
| `transaction_type`, `channel` | string | Activity metadata |
| `country` | char(2)/null | Transaction context |
| `counterparty_id`, `device_id` | FK/null | Optional related entities |
| `counterparty_account_id` | string/null | External opaque account reference |
| `ml_eligible` | boolean | Always false for Phase 1 synthetic AML rows |
| `ml_feature_ref` | string/null | Required only when `ml_eligible=true` |
| `data_source` | string | `synthetic` or future `ulb_attached` |
| `seed_run_id` | FK | Required provenance back to `dataset_runs` |

Indexes cover transaction time, customer/time, account/time, amount, type, country, and ML eligibility.

### Phase 8-ready lifecycle stubs

- `investigations`: request, query, route, status, and UTC lifecycle timestamps.
- `alerts`: entity, risk snapshot, escalation, policy version, and a unique idempotency key.
- `alert_events`: append-only status transition evidence with reviewer, reason, request, evidence version, and risk-policy version. Index: `(alert_id, timestamp)`.

Phase 1 creates storage only; it does not implement later risk or lifecycle behavior.

## Synthetic AML Bundles

Runtime bundles contain customers, profiles, accounts, counterparties, devices, and transactions. They contain no `scenario_label`, `is_suspicious`, injected-pattern field, or expected outcome. Offline manifests under `data/evaluation/` contain scenario annotations and are read only by `backend/evaluation/`.

`scenario_catalog.v1` uses fixed UTC windows. `reporting_thresholds.v1` defines an explicitly illustrative USD 10,000 threshold (`1,000,000` cents), not legal guidance. Seeds `42` and `99` identify development and held-out populations.

## ULB ML Schema

The source contract is exactly 31 ordered columns:

1. `Time`
2. `V1` through `V28`
3. `Amount`
4. `Class` (`0` clean, `1` fraud)

All values are finite and non-null; `Amount` is non-negative. The pinned source has 284,807 rows, 492 fraud rows, and SHA256 `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`.

Exact duplicates are grouped by all 30 non-label fields before the deterministic 70/15/15 split. `Class` never enters grouping. Test features and labels are stored separately; training code does not open test labels.

### `preprocessing.v1`

- Requires exact ordered input `Time`, `V1`–`V28`, `Amount`.
- Drops dataset-specific `Time`.
- Passes `V1`–`V28`.
- Converts non-negative `Amount` to `log1p_Amount`.
- Fits `StandardScaler` on training rows only.
- Outputs the fixed order `V1`–`V28`, `log1p_Amount` (29 features).

Artifact metadata records input/output order, raw and assignment SHA256 values, preprocessing/model versions, threshold recipe, seed, train/validation counts, library versions, and measured validation metrics. `ml_score` is a model ranking score, not a calibrated probability.
