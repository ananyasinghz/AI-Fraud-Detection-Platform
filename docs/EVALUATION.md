# Evaluation

**Status:** Phase 4 investigation state graph and execution traces verified

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

Current result: 191 tests passed with 90.85% branch-aware coverage. Importing the FastAPI app
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
- intent/filter extraction and planner tool-selection accuracy
- transaction and customer risk results
- naive baseline versus contextual detector false-positive comparison on frozen held-out data
- explanation citation/faithfulness
- p50/p95 end-to-end latency

Development and held-out scenario populations remain separate. No expected result is presented as a measured detector result.
