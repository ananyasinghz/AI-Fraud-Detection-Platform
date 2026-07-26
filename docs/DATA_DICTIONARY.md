# Data Dictionary

**Status:** Phase 6 validated dynamic planner implemented
**Contract version:** `v1`

This document covers the frozen boundary contracts, relational and ULB ML schemas, Phase 2
query-scoping/feature/statistics/rules contracts, Phase 5 NL → intent → route → template plans,
and Phase 6 dynamic planning/validation.

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

## QueryScope

`QueryScope` resolves normalized filters before repositories or feature operations run.
Transaction windows are UTC and half-open: `start_inclusive <= occurred_at < end_exclusive`.
Entity, country, type, direction, channel, currency, and amount predicates are intersected;
an empty intersection is represented explicitly and short-circuits database access. Results
use stable `(occurred_at, transaction_id)` ordering with bounded `limit` and `offset`.

Decimal filter amounts are converted to integer minor units only when a currency is explicit.
Values with precision beyond that currency's minor unit are rejected. No FX conversion occurs.

## Feature Operations

`FeatureRequest` contains an operation/version, UTC `as_of`, half-open `FeatureWindow`, explicit
`EntityScope`, transaction predicates, and optional grouping dimensions. `FeatureResult` returns
typed values, named denominators, machine-readable warnings, and provenance including a stable
query identifier, dataset fingerprint, operation version, and policy version.

The `v1` registry provides transaction and rolling aggregates, amount statistics, period
comparison and rates, cash-deposit and sub-threshold activity, round-number and rapid-cash-out
signals, distinct dimensions, profile comparisons, account tenure, profile completeness, and
data-sufficiency indicators. Empty, mixed-currency, or insufficient inputs remain explicit
warning-bearing results and never widen scope.

## Statistical Signals and Rules

Robust statistics use deterministic `Decimal` arithmetic. Available descriptive signals are
median absolute deviation/robust z-score, type-7 IQR bounds, and trailing-baseline deviation.
Zero dispersion or baseline values produce warnings and nullable outputs, never risk labels.

Deterministic rules consume supplied feature results and external policy only. `RuleResult`
records rule/version, fired state, severity, entity, features and thresholds used, evidence
references, and a reason code. Rules do not query storage or repeat feature aggregation.
Profile deviation requires sufficient observed data and a material activity mismatch; PEP,
KYC rating, and residence country cannot independently fire it.

## ParsedIntent

Contains one allow-listed intent, target scope, normalized filters, parser confidence, extracted entities, ambiguities, and parser version.

### Phase 5 NL pipeline

Free-text requests omit `plan`. Orchestration (`backend/app/services/routing.py`) runs:

1. **Intent parser** (`backend/app/nlu/intent_parser.py`) — optional Ollama HTTP client
   (`FRAUD_OLLAMA_*`); injectable transport for tests. One retry on malformed JSON, then the
   deterministic fallback extractor (`backend/app/nlu/fallback.py`). When
   `FRAUD_OLLAMA_ENABLED=false` (default), only the fallback runs.
2. **Date normalizer** (`backend/app/nlu/date_normalizer.py`) — resolves relative tokens such as
   `last_30_days` / `this_month` / `last_7_days` from request `as_of` into UTC half-open
   `date_from`/`date_to`. Absolute dates pass through. No LLM calendar math.
3. **Enum/ID validation** — invalid customer/transaction IDs and enums are dropped with an
   ambiguity note; scope is never silently widened to the full dataset.
4. **Deterministic router** (`backend/app/nlu/router.py`) — maps `ParsedIntent` + confidence/
   ambiguities to `RouteType`, merged `NormalizedFilters`, and a **preferred** template
   `ValidatedPlan`. When no template applies but the case is plannable (e.g. simple lookup by
   transaction id), returns `plan=None` with `needs_planner=true`. Low confidence, invalid IDs,
   and explanation requests (Phase 8) clarify without invoking the planner.
5. **Templates** (`backend/app/nlu/templates.py`) — named deterministic plans for common intents.
   Example: “Show me transactions over $10,000” → SQL-only `list_transactions` (EDA/anomaly
   omitted). Templates are preferred over the dynamic planner when present.
6. **Dynamic planner** (`backend/app/planning/`) — when `needs_planner` and no template: optional
   Ollama plan JSON → semantic validator → execute; on failure after one retry, safe template
   fallback (never “run every tool”). Feature-only / SQL-only plans never inject risk tiers.

When `plan` is supplied, Phase 4 behavior is preserved (manual `ValidatedPlan` → graph executor;
optional `detected_intent` / route override). Clarification failures surface as HTTP 422 with
error code `CLARIFICATION_REQUIRED`.

### Ollama / intent / planner settings

| Setting | Env | Default | Notes |
|---|---|---|---|
| `ollama_enabled` | `FRAUD_OLLAMA_ENABLED` | `false` | Shared by intent + planner HTTP |
| `ollama_base_url` | `FRAUD_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | HTTP via `httpx` |
| `ollama_model` | `FRAUD_OLLAMA_MODEL` | `llama3.2` | Small instruct model |
| `ollama_timeout_seconds` | `FRAUD_OLLAMA_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `intent_confidence_floor` | `FRAUD_INTENT_CONFIDENCE_FLOOR` | `0.55` | Below → clarify |
| `intent_parser_version` | `FRAUD_INTENT_PARSER_VERSION` | `intent_parser.v1` | Provenance string |
| `planner_enabled` | `FRAUD_PLANNER_ENABLED` | `false` | CI uses template fallback |
| `planner_version` | `FRAUD_PLANNER_VERSION` | `dynamic_planner.v1` | Provenance string |
| `planner_max_steps` | `FRAUD_PLANNER_MAX_STEPS` | `20` | Hard cap on plan length |

### Planner whitelist and validation

MVP whitelist (schemas only; no live Python callables in the prompt): `sql_lookup`,
`feature_engineering`, `eda`, `anomaly_detection` with registry operations. Rejected at plan
time: `risk_classification`, `explanation`, `graph_analysis`, `retrieval`, and other Phase 7/8
tools. Semantic checks also reject unknown operations, missing entity parameters, over-broad EDA
on entity-scoped intents, and empty/oversized plans. Domain `ValidatedPlan` still rejects cycles
and duplicate identical steps.

Labeled NL fixtures: `backend/tests/fixtures/intent_queries.v1.json`. Offline metrics:
`backend/evaluation/intent_evaluation.py` and `backend/evaluation/planner_evaluation.py` (never
imported under `backend/app`).

Query/investigation create responses may include optional `parsed_intent`, `route`,
`clarification`, and `needs_planner` alongside the existing `execution_summary`.

## ValidatedPlan

A plan has 1–20 unique acyclic steps. Each step contains:

- unique `step_id`
- allow-listed `tool`
- validated operation name
- JSON-compatible parameters
- dependencies
- concise reason
- required/optional flag

Identical tool operations and dependency cycles are invalid. Phase 6 adds semantic whitelist and
scope checks in `backend/app/planning/validator.py` before execution.

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

### Phase 3–4 lifecycle APIs

- `investigations`: request, query, route, status (`running|completed|partial|failed`), and UTC
  lifecycle timestamps.
- `investigation_runs` (Alembic `0002`): one plan execution with plan snapshot, route, intent,
  terminal status, timings, `execution_summary_json`, and `final_answer`. Optional FK to
  `investigations` (null for ad-hoc `/query` runs).
- `investigation_step_events`: append-only trace events
  (`planned|running|succeeded|failed|skipped|timed_out`) with reason, attempt, duration, and
  optional `tool_result_json`. Source of truth for `ExecutionSummary`.
- `alerts` / `alert_events`: unchanged from Phase 3 (provisional risk placeholders; append-only
  disposition history).

Phase 3 JSON sidecars under `data/runtime/investigation_results/` are read only as a one-release
fallback when no DB run exists.

### Tool and HTTP contracts

Registered tools (common `ToolResult` envelope): `sql_lookup`, `feature_engineering`, `eda`,
`anomaly_detection`, plus Phase 8 stubs `risk_classification` and `explanation` that return
`SKIPPED` with `PHASE_8_NOT_IMPLEMENTED`. Graph nodes may also skip Phase 7 tools with
`PHASE_7_NOT_IMPLEMENTED`.

Workflow skip reasons include `DEPENDENCY_FAILED`, `DEPENDENCY_SKIPPED`, `NODE_TIMEOUT`, and
tool-local reasons. Required-tool failure/skip yields `partial`/`failed`; optional failure
degrades and continues.

- `POST /api/v1/query` — optional `plan`: if omitted, NL parse → route → template plan → graph;
  if provided, Phase 4 manual-plan path. Returns `execution_summary` and optional NL fields.
- `POST|GET /api/v1/investigations[/{id}]` — same optional-`plan` create path; retrieve with
  DB-backed traces and summary.
- `GET /api/v1/customers/{id}`, `GET /api/v1/transactions/{id}`
- `POST /api/v1/transactions/{id}/score` — scores `ml_eligible` rows with resolvable
  `ml_feature_ref` (`fixture:<file>:<row>`); otherwise `skipped` with reason.
- `GET|POST|PATCH /api/v1/alerts` — idempotent create, queue, detail, and audited transitions
  through `open|in_review|escalated|dismissed|closed`.

EDA may emit `ChartSpec` objects. Class/scenario label balance is skipped unless
`allow_labels=true`, and runtime tables still never expose held-out labels. Aggregate responses
are informational only until Phase 8 risk classification.

## Synthetic AML Bundles

Runtime bundles contain customers, profiles, accounts, counterparties, devices, and transactions. They contain no `scenario_label`, `is_suspicious`, injected-pattern field, or expected outcome. Offline manifests under `data/evaluation/` contain scenario annotations and are read only by `backend/evaluation/`.

`scenario_catalog.v1` uses fixed UTC windows. `reporting_thresholds.v1` defines illustrative,
versioned jurisdiction/currency thresholds for the Phase 2 rules, including a USD 10,000
reporting threshold (`1,000,000` cents); it is not legal guidance. Seeds `42` and `99` identify
development and held-out populations.

The evaluation-only `naive_baseline.v1` applies one frozen amount threshold and one UTC
customer/day transaction-count threshold to label-free runtime bundles. It is not a runtime
tool, does not create alerts, and does not accept held-out manifests or labels.

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
