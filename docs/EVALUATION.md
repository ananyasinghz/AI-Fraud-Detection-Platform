# Evaluation

**Status:** Phase 6 validated dynamic planner verified

## Phase 1 Verification

The fixture suite covers migrations, foreign keys and indexes, profile as-of resolution, interval overlap rejection, missing-profile warnings, seed idempotency, scenario reproducibility, hidden-label boundaries, immutable ULB validation, duplicate-group isolation, preprocessing parity, validation-only thresholding, artifact reload, strict schema failures, and batch/single scorer parity.

## Phase 2 Verification

The Phase 2 fixture suite adds coverage for:

- UTC half-open scopes, filter intersections, empty-scope SQL short-circuiting, stable pagination,
  amount/minor-unit conversion, and effective-dated segment filtering
- all 27 named/versioned feature operations with hand-calculated values, denominators, warnings,
  provenance, boundary timestamps, mixed currencies, and deterministic repeated dispatch
- Decimal MAD/robust z-score, type-7 IQR, and trailing-baseline deviation, including empty,
  insufficient, and zero-dispersion cases
- seven deterministic rules with below/equal/above threshold checks, direct feature-result
  parity, provenance preservation, unscoped aggregate rejection, and PEP-only negative coverage
- the evaluation-only fixed-threshold baseline with UTC day grouping, currency isolation,
  deterministic serialization, and held-out-label/import boundaries

## Phase 3 Verification

The Phase 3 fixture suite adds coverage for:

- tool registry unknown tool/operation rejection, dependency-ordered plan execution, envelope
  duration/provenance, and Phase 8 stub `SKIPPED` reasons
- SQL/feature/EDA/anomaly facades with scope propagation, real `ChartSpec` outputs, label-gated
  EDA, ML skip reasons for synthetic/`ml_eligible=false` rows, and hybrid paths
- API contracts for query/investigation/score/alert models
- httpx `TestClient` integration: distinct investigation tool traces, customer/transaction GET,
  ineligible score skip, eligible ULB fixture score success, alert create idempotency, missing
  reason rejection, invalid transitions, and append-only history matching current status
- ULB-attached seed helper using `fixture:creditcard_tiny.csv:<row>` (test-only; not default
  generation)

## Phase 4 Verification

The Phase 4 fixture suite adds coverage for:

- route→intent mapping, append-only traces, and `ExecutionSummary` derived from executor state
- dependency skip reasons, optional vs required failure, no double step dispatch, timeout
  `timed_out` events, and one bounded retry for retryable failures
- regression parity of happy-path SQL payloads between `ToolRegistry.dispatch` and the graph
- API integration: distinct `tools_invoked` sets for feature-only vs SQL-only plans, persisted
  summary on GET, and `/query` returning `execution_summary`
- Alembic `0002` investigation run/step-event tables

## Phase 5 Verification

The Phase 5 suite adds coverage for:

- UTC date normalization of relative tokens (`last_30_days`, `this_month`, `last_7_days`) from
  request `as_of` into half-open filter windows (no LLM calendar math)
- Ollama parser transport injection: success path, one retry on malformed JSON, then deterministic
  fallback; disabled Ollama uses fallback only
- Deterministic router templates for the six mandatory NL queries, including SQL-only
  `list_transactions` for “Show me transactions over $10,000” (no EDA/anomaly)
- Invalid/ambiguous IDs and low-confidence queries return clarification (`needs_planner` /
  HTTP 422 `CLARIFICATION_REQUIRED`) without silently broadening to dataset EDA
- Free-text `POST /api/v1/query` without `plan` (parse → route → template → graph) and unchanged
  explicit-`plan` Phase 4 behavior

### Offline intent metrics (`intent_queries.v1`)

Labeled set: `backend/tests/fixtures/intent_queries.v1.json` (32 queries, including the six
mandatory strings and paraphrases/invalid IDs). Evaluator:
`python -m backend.evaluation.intent_evaluation` (eval-only; not imported by the app).

Measured on the offline deterministic fallback extractor (`FRAUD_OLLAMA_ENABLED=false`):

| Field | Accuracy | n |
|---|---:|---:|
| intent | 1.000 | 32 |
| entity_ids | 1.000 | 11 |
| dates (relative → window) | 1.000 | 6 |
| pattern_type | 1.000 | 4 |
| transaction_type | n/a | 0 |
| route | 1.000 | 30 |

These scores are fixture-regression metrics for the fallback+router path, not a claim about
live Ollama quality. When Ollama is enabled, the same labels remain the evaluation target.

## Phase 6 Verification

The Phase 6 suite adds coverage for:

- Semantic plan validator: whitelist (sql/feature/eda/anomaly only), unknown ops, Phase 8 tool
  rejection, over-broad EDA on entity scope, empty/invalid schemas, domain cycle/duplicate checks
- Dynamic planner with injectable Ollama transport: success, one retry on malformed JSON, then
  deterministic safe-template fallback; `FRAUD_PLANNER_ENABLED=false` uses fallback only
- Template-preferred routing: common intents (including “>$10,000” SQL-only) still use Phase 5
  templates; `needs_planner` path (e.g. transaction-id simple lookup) runs planner → validator →
  execute with filter propagation
- Explanation requests still clarify (Phase 8); low-confidence vague queries still 422
- Forced-planner mandatory invoke/skip regression for the six roadmap queries

### Offline planner tool-selection metrics

Evaluator: `python -m backend.evaluation.planner_evaluation` (force planner+validator; Ollama
disabled → safe template fallback). Same labeled fixture; clarification rows skipped.

Measured (`FRAUD_OLLAMA_ENABLED=false`, force fallback plans):

| Measure | Value | n |
|---|---:|---:|
| tool-set precision | 1.000 | 27 |
| tool-set recall | 1.000 | 27 |
| exact tool-set match | 1.000 | 27 |

These are fixture-regression metrics for the fallback planner path, not live Ollama planner quality.

Current result: 232 tests passed with 90.67% branch-aware coverage. Importing the FastAPI app
still does not load `backend.app.ml*` or `backend.evaluation*` (`scripts/verify_environment.py`).
Ruff formatting/lint, strict mypy, and `alembic check` pass with no schema drift.

## ULB Card-Fraud Benchmark

Raw SHA256: `76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`  
Split assignment SHA256: `ec4c1505cb74e61c7bcb99d922c48cac153aaafb6f6c1065b8037c7befd55b44`

The 70/15/15 split is stratified at exact-feature-group level. Thresholds and candidate selection use validation data only. Test labels are opened only in `backend/evaluation/ml_evaluation.py`.

| Frozen test measure | Logistic regression | Random Forest |
|---|---:|---:|
| PR-AUC | 0.761853 | 0.891986 |
| ROC-AUC | 0.984458 | 0.990645 |
| Precision | 0.191977 | 0.062009 |
| Recall | 0.905405 | 0.959459 |
| F1 | 0.316785 | 0.116489 |
| Alert rate | 0.8174% | 2.6818% |
| False positives | 282 | 1,074 |
| False negatives | 7 | 3 |

Random Forest is selected by validation PR-AUC, not test performance. Its low validation-frozen threshold satisfies the recall-floor objective but creates many more false positives. PR-AUC is the primary ranking measure; the operating threshold remains a policy trade-off. See `docs/MODEL_CARD.md` for full interpretation and prohibited claims.

## Synthetic AML Track

Seed `42` produces 58 customers, 59 effective-dated profiles, 58 accounts, 80 counterparties, 58 devices, and 1,158 transactions with runtime fingerprint:

`861da8d8d4801e8cb625de1e76c5009d5fc15c9e460dbaa8414f4ce10cfb091c`

The generated catalog includes clean controls and nine injected scenario families. Phase 2
provides independently callable features and rules, but this phase does not tune or report
held-out pattern precision/recall. Hidden manifests remain evaluation-only, and no expected
signal is presented as a measured detector result.

## Pending for Later Phases

- synthetic scenario detection results by pattern
- live Ollama planner quality (beyond offline fallback tool-selection metrics)
- transaction and customer risk results
- naive baseline versus contextual detector false-positive comparison on frozen held-out data
- explanation citation/faithfulness
- p50/p95 end-to-end latency

Development and held-out scenario populations remain separate. No expected result is presented as a measured detector result.
