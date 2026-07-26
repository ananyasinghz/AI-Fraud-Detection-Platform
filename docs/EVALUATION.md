# Evaluation

**Status:** Phase 9 demo wiring and held-out FP comparison measured locally

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
  duration/provenance, and Phase 8 tool registration (verification/risk/escalation/explanation)
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

- Semantic plan validator: whitelist including Phase 8 tools, unknown ops, informational-intent
  rejection of Phase 8 chain, Stage-2/escalation/explanation dependency checks, over-broad EDA on
  entity scope, empty/invalid schemas, domain cycle/duplicate checks
- Dynamic planner with injectable Ollama transport: success, one retry on malformed JSON, then
  deterministic safe-template fallback; `FRAUD_PLANNER_ENABLED=false` uses fallback only
- Template-preferred routing: common intents (including “>$10,000” SQL-only) still use Phase 5
  templates; `needs_planner` path (e.g. transaction-id simple lookup) runs planner → validator →
  execute with filter propagation
- Explanation requests with entity scope plan through investigation+Phase 8 chain; without scope
  they clarify; low-confidence vague queries still 422
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

## Phase 7 Verification

The Phase 7 suite adds coverage for:

- NetworkX relationship graph built from scoped SQL (`owns`, `transferred_to`, `used_device`,
  `contacted_counterparty`) with `shared_device`, `circular_transfers`, `two_hop_exposure`, and
  `connected_accounts` operations
- Empty-scope and disabled-flag honest skips (`EMPTY_GRAPH_SCOPE`, `GRAPH_DISABLED`,
  `RETRIEVAL_DISABLED`) — no fabricated hits
- Policy corpus load + deterministic HashingVectorizer retrieval (`search_policy`) with metadata
  and `POLICY_CONTEXT_ONLY` disclaimer
- Registry/workflow execution of graph + retrieval (no `PHASE_7_NOT_IMPLEMENTED`)
- Deliberate seed relationships for shared device, circular transfers, and two-hop exposure;
  gold fixture `backend/tests/fixtures/graph_relationships.v1.json` (eval-only)
- Planner whitelist includes graph/retrieval; SQL-only “>$10,000” templates still exclude them;
  entity/broad templates may include optional graph/retrieval steps (`required=false`)

### Graph / retrieval smoke

| Check | Result |
|---|---|
| Shared-device gold (seed 42) | recovered |
| Circular-transfer gold (seed 42) | recovered |
| Two-hop exposure gold (seed 42) | recovered |
| Policy search for structuring/threshold query | ≥1 metadata-bearing hit |

Current result: see latest local gate after Phase 8 (pytest ≥90%, ruff, mypy, alembic check,
`scripts/verify_environment.py`). Importing the FastAPI app still does not load `backend.app.ml*`
or `backend.evaluation*`.

## Phase 8 Verification

The Phase 8 suite adds coverage for:

- Stage-1 evidence verification: unresolved refs, scope mismatch, missing versions, invalid
  structure, insufficient-data confidence caps, forbidden label fields
- Points-model transaction risk boundaries (`ml_score` vs `risk_score`), customer_rollup.v1
  (event_peak, pattern_breadth, recency decay, duplicate-rule suppression, profile missingness,
  KYC context cannot alone force HIGH, exact tier cutoffs)
- Stage-2 consistency: tier reproduce, invalid weights reject, context-only downgrade, weak-data
  HIGH → review posture
- Escalation mapping LOW/MEDIUM/HIGH → monitor/review/report; idempotent alert create for
  review/report with verified snapshot overlay
- Explanation citation OK; hallucinated rule/evidence → template fallback; Ollama-down →
  deterministic template
- Workflow/API: suspicious plans invoke verification/risk/escalation/explanation; SQL-only omits
  them; dual-verified findings surface as `FlaggedResult`

Frozen demo risk metrics are evaluated on development scenarios only; held-out once fixtures exist.
See [`docs/RISK_MODEL.md`](RISK_MODEL.md).

Current local gate (Phase 9): 273 tests passed with 90.58% branch-aware coverage. Importing the
FastAPI app still does not load `backend.app.ml*` or `backend.evaluation*`
(`scripts/verify_environment.py`). Ruff formatting/lint, strict mypy, and `alembic check` pass.

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

Seed `42` produces 64 customers, 65 effective-dated profiles, 64 accounts, 81 counterparties, 65 devices, and 1,164 transactions with runtime fingerprint:

`10864b4b2007711b3e3b3b2730dc0a32635c1401999e0578c18f943fed1de6ea`

(Counts include Phase 7 deliberate graph-relationship customers/devices/transfers.)

The generated catalog includes clean controls and nine injected scenario families. Phase 2
provides independently callable features and rules, but this phase does not tune or report
held-out pattern precision/recall. Hidden manifests remain evaluation-only, and no expected
signal is presented as a measured detector result.

## Pending for Later Phases

- live Ollama planner quality (beyond offline fallback tool-selection metrics)

Development and held-out scenario populations remain separate. No expected result is presented as a measured detector result.

## Phase 9 Evaluation

Demo UI, six-query e2e traces, held-out false-positive comparison, citation checks, and local
latency harness. Stretch feedback loop and PDF export are out of scope.

### Reused prior metrics

Intent/filter extraction, planner tool-selection, and ULB ML tables above remain authoritative.
Phase 8 unit suites cover dual-gate risk, rollup, consistency, escalation, and explanation
citation/fallback behavior.

### Explanation citation / faithfulness

Unit suite (`test_explanation_citation_and_fallback`, Phase 8 coverage): cited `evidence_ids`
must be in the allowed verified set; hallucinated refs force `template_fallback`. Offline
check: 100% of template explanations in the fixture suite cite only verified ids; Ollama path
rejects uncited claims before surfacing. Faithfulness is structural citation validity, not an
external LLM-as-judge score.

### Risk / customer-rollup (held-out, development-frozen policy)

Policy `config/policy/risk_scoring.v1.yaml` (`customer_rollup.v1`) was frozen on development
scenarios. Held-out customer scan (seed 99) uses the same file via
`python -m backend.evaluation.heldout_fp_comparison`. Measured contextual alert rates appear in
the table below—report measured values only; no aspirational reduction claim.

### Held-out AML false-positive comparison (seed 99)

Reproduce:

```powershell
python -m backend.evaluation.heldout_fp_comparison --seed 99
```

Output: `data/evaluation/held_out/fp_baseline_seed-99.json`.

| Metric | Naive fixed-threshold baseline | Contextual detector |
|---|---:|---:|
| Alerts raised | 2 | 2 |
| True positives | 2 | 2 |
| False positives | 0 | 0 |
| False-positive rate `FP / (FP + TN)` | 0.000 | 0.000 |
| Alerts per 1,000 evaluated entities | 31.25 | 31.25 |
| Precision | 1.000 | 1.000 |
| Recall | 0.095 | 0.095 |

Population: 64 customers; 21 annotated positives (prevalence 0.328). Runtime fingerprint
`8994208cd26e75172ad1c875b44f0b60f9c932cddd01ecc9f0ad2e8e982c300d`. Measured 2026-07-26 on a
local developer machine (`as_of=2026-07-25Z`).

**Limitations / prevalence:** synthetic injected scenarios; positives are annotated customers with
`pattern_type != clean_control`. Naive baseline flags fixed amount / daily-count thresholds with
no profile context. Contextual path runs entity-scoped structuring features + `structuring.v1`
rules + Phase 8 risk/escalation (anomaly facade is structuring-focused today), so held-out recall
is low and matches the naive alert count on this cut—not an aspirational FP reduction. Rules/profile
ablation: profile/context remain ≤5% of rollup when supplied; no separate numeric ablation beyond
the contextual row. ML incremental effect: synthetic AML rows are `ml_eligible=false`, so not
measurable here.

### Six mandatory queries (e2e)

`backend/tests/integration/test_phase9_six_queries.py` asserts distinct
`tools_invoked` / skipped traces for the six demo chips (seed-42 IDs). Latency harness:

```powershell
python scripts/measure_demo_latency.py
```

Writes `data/evaluation/dev/latency_six_queries.json` with p50/p95 ms per query type (local
machine caveat; Ollama off). Latest local sample (n=3, seed 42, `as_of=2026-07-25Z`):

| Query type | p50 ms | p95 ms |
|---|---:|---:|
| sql_only_amount | 36 | 79 |
| threshold_aggregation | 49 | 52 |
| feature_only_spend | 29 | 33 |
| structuring (scoped) | 42 | 54 |
| entity_investigation | 78 | 3085 |
| broad_eda | 88 | 89 |

Entity investigation p95 is inflated by a cold first call (graph/retrieval warm-up); repeat
calls sit near the p50.

### Demo path

`python scripts/prepare_demo.py` + README Demo section. Frontend `npm run build` typechecks the
live API client.
