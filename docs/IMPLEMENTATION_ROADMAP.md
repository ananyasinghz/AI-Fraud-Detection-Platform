# Implementation Roadmap — AI-Powered Suspicious Activity Detection Platform

**Audience:** Two fourth-year CS students building a hackathon/research MVP  
**Architecture principle:** Deterministic-first, LLM-at-the-edge  
**Status:** Corrected implementation blueprint after repository and requirements audit  
**Estimated duration:** Six weeks at approximately 15–20 hours per developer per week

---

## 1. Outcome and Non-Negotiable Requirements

The finished system must accept a natural-language instruction, extract its intent and scope, construct a query-specific execution plan, invoke only the necessary tools, and return auditable suspicious-activity findings.

The final product must demonstrate all of the following:

1. Query parsing for intent, dates, customer/account/transaction IDs, country, segment, transaction type, and AML pattern.
2. Dynamic tool selection rather than a fixed SQL → Rules → ML pipeline.
3. Query-scoped data loading and preprocessing.
4. Selective EDA for broad exploration, skipped for targeted requests.
5. On-demand AML feature engineering.
6. Rule-based, statistical, ML, or hybrid anomaly detection.
7. Transaction-level and customer-level risk classification.
8. Evidence-grounded explanations.
9. Deterministic escalation recommendations: `monitor`, `review`, or `report`.
10. A structured execution summary showing what the agent understood, invoked, skipped, and why.
11. Supporting tables, metrics, and at least a minimal set of charts.

The LLM may parse, plan, and explain. It must not calculate authoritative AML metrics, set risk tiers, or choose escalation actions without deterministic validation.

---

## 2. Repository Audit and ML Decision

### 2.1 What is currently present

The workspace currently contains reference material, not an implemented AML application:

- `dataset/creditcard.csv`: the ULB/Kaggle credit-card fraud dataset.
- `Fraud Detection/`: an imported third-party research repository.
- Five serialized model bundles under the imported repository's `saved_models/`.
- No application backend, frontend, root Git repository, tests, or persisted architecture document existed before this roadmap.

### 2.2 Decision: do not use the imported repository as a runtime dependency

The imported repository is useful as a learning and comparison reference, but it is not safe to integrate as-is:

- It is not a Python package and has no inference service.
- No license is supplied, so its source and model artifacts must not be assumed redistributable.
- Its expected train/test split files are absent.
- Its test script is broken and expects a model-bundle key that does not exist.
- Its reported threshold is selected on the test set, making threshold-dependent metrics optimistically biased.
- Its probabilities are not calibrated.
- Its actual preprocessing drops `Time`, applies `log1p(Amount)`, and adds `V17_V14`; this contradicts the original roadmap's claimed input contract.
- The serialized bundle uses `pickle` with `pipeline`, `threshold`, and `model_name` keys, not `joblib` with a raw model.
- PCA features `V1`–`V28` cannot provide human-readable AML explanations by themselves.

### 2.3 Correct ML approach

Use the repository only as an attributed reference. Independently implement and retrain a compact supervised fraud scorer on `creditcard.csv`:

1. Preserve the raw dataset unchanged.
2. Create reproducible train, validation, and test partitions.
3. Keep exact duplicate groups in one partition to prevent duplicate leakage.
4. Fit preprocessing on training data only.
5. Select the alert threshold on validation data only.
6. Evaluate once on the untouched test set.
7. Serialize the complete preprocessing-plus-model contract.
8. Call the model output `ml_score` unless calibration is explicitly implemented and tested; do not call it a calibrated probability.
9. Use the Random Forest as the default MVP model because it is small and has fast inference. Compare against a simple logistic-regression baseline.
10. Treat model evidence as one optional signal. It does not replace AML feature engineering or deterministic rules.

The imported `.pkl` may be used temporarily for local comparison after reproducing its exact 30-feature preprocessing, but it is not a deliverable and must not be the production path.

### 2.4 Two evaluation tracks

The ULB dataset is a card-fraud benchmark, not an AML entity-history dataset. It has no customers, accounts, transaction types, countries, counterparties, or cash-deposit semantics. Do not claim that its `Class` label proves structuring or smurfing detection.

Use two clearly separated tracks:

- **ML benchmark track:** immutable ULB rows for supervised transaction-fraud scoring and honest model evaluation.
- **AML scenario track:** reproducibly generated customers, accounts, counterparties, countries, channels, and transactions containing known clean and suspicious scenarios for feature/rule/agent evaluation.

The AML generator may attach randomly selected benchmark transactions to synthetic accounts for demo continuity, but must not group records using `Class` or expose scenario labels to detection code. Synthetic AML transactions that lack model features must be marked `ml_eligible=false`; the planner then skips the ML scorer for those records.

---

## 3. Final Build Order

```text
Phase 0  Contracts, repository, environment, and documentation
Phase 1  Data foundation, AML scenario generator, and corrected ML pipeline
Phase 2  Query scoping, feature engineering, and deterministic rules
Phase 3  First-class tools and backend API
Phase 4  Investigation state graph and execution tracing
Phase 5  Intent extraction and deterministic routing
Phase 6  Validated dynamic planner
Phase 7  Relationship graph and policy retrieval (optional extension)
Phase 8  Risk, verification, escalation, and grounded explanation
Phase 9  Frontend, reports, evaluation, and demo hardening
```

Feature Engineering and Anomaly Detection are first-class orchestrated tools throughout the system. Risk and escalation are introduced to the planner only after their Phase 8 nodes exist.

---

## 4. Canonical Project Structure

The imported GitHub repository must not become an application module. First-party application code and reference material remain separate.

```text
fraud/
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── docker-compose.yml                 # optional until Neo4j is enabled
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   └── routes/
│   │   │       ├── health.py
│   │   │       ├── query.py
│   │   │       ├── investigations.py
│   │   │       ├── alerts.py
│   │   │       ├── customers.py
│   │   │       └── transactions.py
│   │   ├── core/
│   │   │   ├── config.py
│   │   │   ├── logging.py
│   │   │   └── errors.py
│   │   ├── domain/
│   │   │   ├── enums.py
│   │   │   ├── filters.py
│   │   │   ├── intent.py
│   │   │   ├── plan.py
│   │   │   ├── evidence.py
│   │   │   ├── alerts.py
│   │   │   └── responses.py
│   │   ├── data/
│   │   │   ├── database.py
│   │   │   ├── repositories/
│   │   │   └── query_scope.py
│   │   ├── tools/
│   │   │   ├── registry.py
│   │   │   ├── sql/
│   │   │   ├── eda/
│   │   │   ├── features/
│   │   │   ├── anomaly/
│   │   │   ├── graph/
│   │   │   └── retrieval/
│   │   ├── rules/
│   │   │   ├── base.py
│   │   │   ├── engine.py
│   │   │   └── implementations/
│   │   ├── ml/
│   │   │   ├── preprocessing.py
│   │   │   ├── train.py
│   │   │   ├── evaluate.py
│   │   │   └── fraud_scorer.py
│   │   ├── nlu/
│   │   │   ├── intent_parser.py
│   │   │   ├── date_normalizer.py
│   │   │   └── router.py
│   │   ├── planning/
│   │   │   ├── planner.py
│   │   │   └── validator.py
│   │   ├── workflow/
│   │   │   ├── state.py
│   │   │   ├── graph.py
│   │   │   ├── nodes/
│   │   │   └── execution_trace.py
│   │   ├── risk/
│   │   │   ├── classifier.py
│   │   │   ├── customer_rollup.py
│   │   │   └── escalation.py
│   │   ├── evidence/
│   │   │   ├── aggregator.py
│   │   │   └── verification.py
│   │   ├── explanation/
│   │   │   ├── generator.py
│   │   │   └── faithfulness.py
│   │   ├── feedback/
│   │   │   ├── dispositions.py
│   │   │   └── calibration.py
│   │   └── reporting/
│   │       └── report_generator.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       ├── evaluation/
│       └── fixtures/
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── pages/
│   │   └── types/
│   └── tests/
│
├── data/
│   ├── raw/                            # immutable, gitignored where required
│   ├── interim/
│   ├── processed/
│   ├── splits/
│   └── fixtures/                       # tiny committed test/demo fixtures
│
├── models/                             # generated artifacts + metadata, gitignored
├── scripts/
│   ├── prepare_ml_data.py
│   ├── generate_aml_scenarios.py
│   ├── seed_database.py
│   └── verify_environment.py
├── docs/
│   ├── ARCHITECTURE.md
│   ├── IMPLEMENTATION_ROADMAP.md
│   ├── DATA_DICTIONARY.md
│   ├── RISK_MODEL.md
│   ├── MODEL_CARD.md
│   ├── EVALUATION.md
│   └── THIRD_PARTY_ATTRIBUTION.md
├── third_party/
│   └── references/
│       └── credit-card-fraud-detection/ # read-only reference; never runtime-imported
└── tests/
    └── e2e/
```

The existing nested repository may remain where it is during planning, but implementation should move or archive it under `third_party/references/`. Because no upstream license is present, do not copy its code into first-party modules or redistribute its artifacts without permission.

---

## 5. Shared Contracts Defined Before Implementation

Freeze contract version `v1` during Phase 0. Internal modules may evolve, but all tool results must validate against shared Pydantic schemas.

### Analysis request

```json
{
  "query": "Find structuring patterns in the last 30 days",
  "as_of": "2026-07-25T00:00:00Z",
  "intent": "pattern_search",
  "target_scope": "customer",
  "filters": {
    "date_from": "2026-06-25T00:00:00Z",
    "date_to": "2026-07-25T00:00:00Z",
    "customer_ids": [],
    "account_ids": [],
    "transaction_ids": [],
    "segment": null,
    "country": null,
    "transaction_type": null,
    "pattern_type": "structuring"
  }
}
```

### Validated plan

```json
{
  "strategy": "targeted_pattern_search",
  "steps": [
    {
      "tool": "feature_engineering",
      "operation": "structuring_features",
      "depends_on": [],
      "reason": "Compute only features required for structuring"
    },
    {
      "tool": "anomaly_detection",
      "operation": "rules_only",
      "depends_on": ["feature_engineering"],
      "reason": "Apply structuring thresholds without unrelated ML"
    }
  ]
}
```

### Tool result envelope

Every tool returns:

```json
{
  "tool": "feature_engineering",
  "status": "success",
  "scope": {},
  "data": {},
  "warnings": [],
  "duration_ms": 0,
  "provenance": {
    "source": "sqlite",
    "query_or_version": "feature-contract-v1"
  }
}
```

### Final response

```json
{
  "execution_summary": {
    "query": "",
    "detected_intent": "",
    "filters": {},
    "plan": [],
    "tools_invoked": [],
    "tools_skipped": [],
    "fallbacks": [],
    "warnings": []
  },
  "results": [],
  "supporting_evidence": {},
  "charts": [],
  "answer": ""
}
```

Each flagged result contains `entity_type`, `entity_id`, `risk_score`, `risk_level`, `reasons`, `escalation_action`, `evidence_refs`, and `confidence`. Informational feature-only or SQL-only answers may return no risk tier when no suspicious finding was requested or produced.

---

## 6. Phase-by-Phase Roadmap

## Phase 0 — Contracts, Repository, Environment, and Documentation

### Purpose

Create a reproducible foundation and prevent schema drift before any worker or LLM integration begins.

### Deliverables

- Root Git repository and branch convention.
- Python 3.11 environment managed by `pyproject.toml`.
- Root `.gitignore` excluding raw data, model binaries, database files, secrets, Ollama state, and generated charts.
- `.env.example` with no real secrets.
- FastAPI `/health` endpoint.
- Contract-v1 Pydantic schemas for request, intent, filters, plan, tool results, evidence, execution summary, and final response.
- Persisted architecture, roadmap, data dictionary, and attribution documents.
- CI running formatting, linting, type checks, and unit tests.

### Acceptance criteria

- A fresh environment can start the API from README instructions.
- `/health` returns HTTP 200.
- Contract examples validate in tests.
- Neither the imported repository nor raw dataset is imported from application code.

---

## Phase 1 — Data Foundation, AML Scenarios, and Corrected ML Pipeline

### Purpose

Build honest, reproducible data and model foundations without pretending the card-fraud dataset is an AML dataset.

### Data deliverables

- SQLite for MVP, with migrations for:
  - `customers`
  - `accounts`
  - `transactions`
  - `counterparties`
  - `devices`
  - `investigations`
  - `alerts`
- Customer profiles with synthetic, effective-dated KYC/onboarding attributes:
  - `segment` (`retail`, `sme`, or `corporate`)
  - `residence_country`
  - `occupation_or_industry`
  - `declared_annual_income` or declared revenue band, with currency
  - `expected_monthly_volume_min` and `expected_monthly_volume_max`
  - `kyc_risk_rating`
  - `pep_flag`
  - `account_opened_at`
  - `profile_effective_from`, `profile_effective_to`, and `profile_source`
- UTC timestamps and integer minor currency units or `Decimal`; never binary floating point for business-rule comparisons.
- Explicit fields such as `transaction_type`, `channel`, `country`, `currency`, `counterparty_account_id`, and `ml_eligible`.
- Deterministic AML scenario generator with a fixed random seed.
- Scenario manifest containing hidden ground truth for evaluation only.
- Scenarios for:
  - clean baseline activity
  - structuring just below a configured reporting threshold
  - smurfing across multiple accounts/customers
  - velocity bursts
  - rapid cash-out
  - round-number concentration
  - sudden spending increase
  - activity inconsistent with the customer's declared profile
  - a new account with insufficient history
  - optional high-risk-country activity
- Database indexes on timestamps, customer/account IDs, amount, transaction type, and country.

Thresholds must be configurable by jurisdiction/currency and presented as demonstration policy, not legal advice. Do not hardcode `$10,000` globally.

Customer attributes are contextual evidence, not proof of suspicious activity. `pep_flag`, occupation/industry, country, or a KYC rating must never fire an alert alone. Missing profile values must produce an explicit data-quality warning rather than a zero or an assumed low-risk value. All demo profiles are synthetic; real KYC/PII is out of scope.

### ML deliverables

- Immutable copy of the ULB CSV under `data/raw/`.
- Reproducible leakage-aware train/validation/test split manifest.
- First-party preprocessing contract used identically by training and inference.
- Logistic-regression baseline and Random Forest candidate.
- Validation-only threshold selection.
- Untouched test evaluation reporting PR-AUC, ROC-AUC, precision, recall, F1, confusion matrix, and alert rate.
- Optional probability calibration assessed with reliability curves/Brier score.
- Serialized model plus metadata:
  - schema version
  - feature order
  - preprocessing version
  - model version
  - selected threshold
  - training data fingerprint
- `fraud_scorer.py` with batch and single-transaction APIs.
- Model card stating that the dataset predicts card-fraud labels, not AML typologies.

### Required tests

- Raw-data schema and known row-count validation.
- Duplicate groups never cross split boundaries.
- Training and inference preprocessing produce identical vectors.
- Wrong or missing feature schemas fail loudly.
- Scores are deterministic for a fixed model.
- Evaluation code never accesses the test labels during training or threshold selection.
- Synthetic scenario labels are inaccessible to feature/rule execution code.
- Customer-profile versions are resolved as of the transaction/investigation timestamp.
- Missing income, expected-activity, tenure, and currency cases are handled explicitly.

### Acceptance criteria

- The Random Forest or baseline is reproducibly trained and evaluated.
- No metric from the imported repository is claimed as the project's own result.
- At least one clean and one suspicious scenario can be queried by entity and date.
- Customer EDA can summarize profile completeness and observed-versus-expected activity without exposing hidden scenario labels.

---

## Phase 2 — Query Scoping, Feature Engineering, and Rule Engine

### Purpose

Create reusable, query-aware calculations and thin deterministic rules. Feature computations must remain independently callable for feature-only questions.

### Query-scoping deliverables

- `QueryScope` resolves all filters into an explicit data subset before expensive tools execute.
- All tools receive the same normalized `as_of`, timezone, date boundaries, entity filters, and row limits.
- Empty scopes return a valid no-data result rather than scanning the full database.
- Pagination and maximum-result limits protect broad requests.

### Feature Engineering Tool

Implement a registry of named, versioned feature operations:

- transaction count and total by window
- rolling sum and rolling count
- average, median, maximum, and amount deviation
- current-period versus baseline deviation
- transactions per hour/day
- cash-deposit count and sum
- count/total just below a configured reporting threshold
- round-number ratio
- rapid cash-out ratio and elapsed time
- distinct counterparties, accounts, devices, and countries
- `activity_vs_expected`: observed volume relative to the effective expected monthly range
- `income_to_volume_ratio`: currency-normalized observed volume relative to declared income/revenue, when available
- `account_tenure_days`
- profile completeness and data-sufficiency indicators

Each operation accepts an explicit scope and returns feature values plus window boundaries, denominators, missing-data warnings, and provenance.

Avoid ambiguous signatures such as `rolling_sum(customer_id, days)`. Use a request object containing entity scope, `as_of`, window, transaction types, currency, and optional grouping level.

### Rule Engine

Rules consume feature results and apply configurable policy:

- `StructuringRule`
- `SmurfingRule`
- `VelocityRule`
- `RapidCashOutRule`
- `RoundNumberRule`
- `ProfileDeviationRule`
- optional `HighRiskCountryRule` only when synthetic country data exists

`ProfileDeviationRule` may fire only from a material, configurable observed-versus-declared activity mismatch with sufficient data. PEP/KYC/country context may modify the later risk assessment within documented bounds, but must not independently fire this rule.

Each rule returns:

```json
{
  "rule_id": "structuring.v1",
  "fired": true,
  "severity": "high",
  "entity_type": "customer",
  "entity_id": "C123",
  "features_used": {},
  "thresholds_used": {},
  "evidence_refs": [],
  "reason_code": "MULTIPLE_SUB_THRESHOLD_CASH_DEPOSITS"
}
```

### Statistical anomaly helpers

Add optional robust statistics for context-aware anomaly detection:

- median absolute deviation or robust z-score
- IQR outliers
- current-period deviation from trailing baseline

These produce signals, not final risk labels.

### Naive fixed-threshold benchmark

Implement a separate evaluation-only baseline representing the traditional context-free approach:

- flag every transaction above one fixed amount threshold
- flag every customer above one fixed transactions-per-day threshold
- use no customer profile, rolling baseline, contextual feature, ML score, or planner

This baseline is not registered as an agent tool and is not used to produce application alerts. It exists only for the Phase 9 false-positive comparison. Its thresholds must be chosen on development scenarios and frozen before held-out evaluation.

### Required tests

- Hand-calculated fixtures for every feature.
- Boundary tests exactly below, equal to, and above thresholds.
- Timezone, inclusive/exclusive boundary, empty-history, and insufficient-baseline cases.
- Filter-propagation tests.
- Feature-only query test:
  - “Did customer 123 suddenly increase spending this month?”
  - expected tools: `feature_engineering`
  - skipped: full EDA, unrelated rules, ML
- Rule results must match direct calls to the underlying feature operation.
- Profile fixtures hand-verify income/volume, expected-activity, effective-date, and account-tenure calculations.
- A PEP-only fixture produces no rule hit.
- The naive benchmark is deterministic and cannot access held-out scenario labels while applying thresholds.

### Acceptance criteria

- Features and rules never silently widen scope.
- No rule reimplements aggregation logic.
- Thresholds are external configuration with currency/jurisdiction metadata.
- Profile attributes are treated as bounded context, with missingness and provenance preserved.

---

## Phase 3 — First-Class Tools and Backend API

### Purpose

Expose every required capability behind a common tool interface before introducing dynamic LLM orchestration.

### Required tools

1. **EDA Tool**
   - broad dataset/customer-cohort profiling
   - missingness and schema quality
   - customer-profile completeness, segment/tenure distribution, and observed-versus-expected activity
   - amount and volume distributions
   - transaction volume over time
   - class/scenario balance where labels are explicitly allowed
   - returns chart specifications or generated asset references

2. **Feature Engineering Tool**
   - wraps Phase 2's operation registry
   - supports direct feature-only answers

3. **Anomaly Detection Tool**
   - a facade selecting `rules_only`, `statistical_only`, `ml_only`, or `hybrid`
   - validates that ML is called only for `ml_eligible` records with the expected schema
   - returns individual signals without deciding the final risk tier

4. **Risk Classification Tool**
   - interface defined now; implementation activated in Phase 8

5. **Explanation Component**
   - interface defined now; implementation activated in Phase 8

Supporting tools include targeted SQL lookup, and optionally relationship graph and policy retrieval.

### API deliverables

- `POST /api/v1/query`: natural-language entry point, initially accepts a manually supplied plan for tool testing.
- `POST /api/v1/investigations`: structured deterministic entry point.
- `GET /api/v1/customers/{id}`.
- `GET /api/v1/transactions/{id}`.
- `POST /api/v1/transactions/{id}/score`: transaction ML signal and later risk result.
- `GET /api/v1/investigations/{id}`.
- `GET /api/v1/alerts?status=open`: reviewer queue with pagination and sorting.
- `GET /api/v1/alerts/{id}`: alert, evidence snapshot, history, and current status.
- `PATCH /api/v1/alerts/{id}`: valid status transition with reason and reviewer identity.
- OpenAPI documentation.

Routes contain no business logic. Tool calls use a registry and common result envelope.

Alert states are `open`, `in_review`, `escalated`, `dismissed`, and `closed`. Define allowed transitions rather than accepting arbitrary status strings. Every transition appends an immutable audit event containing timestamp, reviewer ID, reason, previous/new state, evidence version, risk-policy version, and request ID. Alert creation is idempotent on entity + finding + policy version + investigation window so retries do not create duplicates. For the hackathon, use synthetic data and either basic reviewer authentication or an explicitly labeled single-user demo identity; do not imply production-grade access control.

### Important correction

Do not make the final `/investigate` behavior always run SQL, Rules, and ML. A temporary fixed path is allowed only as a development regression fixture. Production endpoints execute an explicit validated tool list.

### Required tests

- API and Pydantic contract tests.
- Tool registry rejects unknown tools/operations.
- Query scope reaches every selected worker unchanged.
- EDA chart results validate against a chart schema.
- Individual transaction scoring and customer aggregation both work.
- Ineligible synthetic records cause ML to be skipped with a recorded reason, not an error.
- Alert creation is idempotent; invalid transitions and missing disposition reasons are rejected.
- Alert history is append-only and the current state matches the latest valid event.

### Acceptance criteria

- Every tool can be invoked and tested independently.
- A deterministic request can produce results without any LLM.
- Minimal required charts and tables are real outputs, not frontend mock data.
- A reviewer can retrieve and transition a synthetic alert through the API with a complete audit history.

---

## Phase 4 — Investigation State Graph and Execution Trace

### Purpose

Execute validated plans conditionally while preserving a complete audit trail.

### State fields

`InvestigationState` includes:

- request and normalized intent
- query scope
- validated plan
- current step and completed steps
- tool results
- evidence references
- warnings and fallbacks
- `tools_invoked`
- `tools_skipped`, each with a reason
- timing and error metadata
- risk, escalation, and explanation placeholders

### Graph nodes

- `sql_node`
- `eda_node`
- `feature_engineering_node`
- `anomaly_detection_node`
- optional `graph_analysis_node`
- optional `retrieval_node`
- `aggregate_node`
- Phase 8 additions: `risk_node`, `verification_node`, `escalation_node`, `explanation_node`

The graph executor reads a validated plan rather than relying on a permanently hardcoded sequence. Dependencies declared in the plan determine ordering; independent safe operations may run in parallel later.

### Reliability requirements

- Node timeout and bounded retry policy.
- Errors become structured tool failures.
- Optional-tool failure may degrade gracefully.
- Required-tool failure produces a partial, clearly marked response.
- Request ID and investigation ID appear in all logs.
- Execution trace is the source of truth for the final execution summary.

### Required tests

- Regression comparison against direct deterministic tool calls.
- Explicit skip behavior.
- No-data and malformed-result behavior.
- Timeout and partial-result paths.
- The same tool is not run twice unless the plan explicitly allows retry.

### Acceptance criteria

- Different plans produce observably different invoked/skipped tool sets.
- The official targeted queries do not traverse unrelated nodes.

---

## Phase 5 — Intent Extraction and Deterministic Router

### Purpose

Translate free text into validated intent and filters. The LLM extracts; deterministic code normalizes and routes.

### Intent schema

Supported intents include:

- `broad_exploration`
- `simple_lookup`
- `threshold_aggregation`
- `feature_comparison`
- `pattern_search`
- `entity_investigation`
- `transaction_scoring`
- `explanation_request`

Supported extracted scope includes dates, relative-date phrases, IDs, segment, country, transaction type, currency, target entity level, pattern type, requested output count, and sort direction.

### Implementation rules

- Use a small local instruction model through Ollama with schema-constrained output where supported.
- Resolve relative dates deterministically from the request's explicit `as_of`; do not ask the LLM to perform calendar arithmetic.
- Validate entity IDs and enum values.
- Retry malformed structured output once, then use deterministic fallback or ask for clarification.
- The router is Python decision logic, not another LLM.
- Low-confidence or materially ambiguous input must not silently broaden scope.

### Required labeled query set

At least 30 queries, including paraphrases, invalid IDs, ambiguous dates, and these mandatory cases:

1. “Find structuring patterns in the last 30 days.”
2. “Which customers made 10+ transactions under $10,000?”
3. “Is customer ID 4521 suspicious?”
4. “Did customer 123 suddenly increase spending this month?”
5. “Show me transactions over $10,000.”
6. “Analyse this dataset for suspicious activity.”

### Acceptance criteria

- Intent, entity, date, pattern, and transaction-type extraction metrics are reported separately.
- Official query expectations include both invoked and skipped tools.
- “Show me transactions over $10,000” routes to targeted SQL only.

---

## Phase 6 — Validated Dynamic Planner

### Purpose

Construct a minimal valid tool plan for requests that cannot be answered by the router's direct deterministic templates.

### Initial planner whitelist

Only tools already implemented may be selected:

- `sql_lookup`
- `eda`
- `feature_engineering`
- `anomaly_detection`
- optional `graph_analysis`
- optional `retrieval`

Risk, verification, escalation, and explanation are added to the whitelist in Phase 8 after their nodes exist.

### Planner rules

- Plans contain tool, operation, parameters, dependencies, and a concise reason.
- The planner receives tool schemas and capability descriptions, not arbitrary Python function access.
- A validator rejects unknown tools, invalid operations, missing dependencies, incompatible scopes, cycles, duplicate work, and unbounded broad scans.
- Direct template plans remain preferred for common known intents.
- On invalid output, use a deterministic safe template; do not run every tool by default.
- Feature-only and SQL-only questions do not receive artificial risk tiers.
- Risk/escalation will later run only when suspicious findings are requested or produced.

### Mandatory expected plans

| Query | Invoke | Skip |
|---|---|---|
| Find structuring patterns in the last 30 days | scoped feature engineering, rules-only anomaly detection | full EDA, unrelated ML |
| Which customers made 10+ transactions under $10,000? | SQL threshold aggregation | EDA, feature engine if SQL suffices, ML |
| Is customer ID 4521 suspicious? | entity SQL, relevant features, anomaly detection | dataset-wide EDA |
| Did customer 123 suddenly increase spending this month? | baseline-deviation feature | EDA, unrelated rules, ML |
| Show me transactions over $10,000 | SQL filter | all analytical tools |
| Analyse this dataset for suspicious activity | EDA, scoped feature/anomaly operations | none without a recorded reason |

### Required tests

- Plan schema and semantic-validator tests.
- Planner tool-selection precision/recall against the labeled query set.
- Filter propagation from intent through plan to tool.
- Malformed, hallucinated, cyclic, and over-broad plan rejection.
- Deterministic fallback behavior.

### Acceptance criteria

- The execution summary accurately explains why each tool ran or was skipped.
- The final agent is demonstrably not a fixed sequential pipeline.

---

## Phase 7 — Relationship Graph and Policy Retrieval (Optional Extension)

### Purpose

Add capabilities that support layering/shared-identity investigations and policy context without endangering the core MVP.

### Graph analysis

- Neo4j Community Edition or an in-memory NetworkX MVP.
- Minimal relationships:
  - customer owns account
  - account transferred to account
  - account used device
  - account contacted counterparty
- Queries for shared device, connected flagged accounts, circular transfers, and two-hop exposure.
- Synthetic AML scenarios must deliberately contain known graph relationships.

### Retrieval

- Small, legally shareable corpus of policy excerpts and reporting guidance.
- Document metadata, source URL, publication date, jurisdiction, and section.
- ChromaDB with a local embedding model.
- Retrieved policy text supports reviewer context; it must not override deterministic evidence or present legal conclusions.

### Cut rule

If core Phase 8 work is at risk, defer Phase 7 entirely. Do not mock graph or retrieval results and present them as real. A clearly marked “not executed/not available” result is safer and more credible.

---

## Phase 8 — Risk, Verification, Escalation, and Grounded Explanation

### Purpose

Convert verified signals into auditable risk outcomes and explain them without letting an LLM invent decisions.

### Risk Classification Tool

Support both transaction and customer scope. Produce:

- normalized `risk_score`
- `LOW`, `MEDIUM`, or `HIGH`
- contributing signals and weights
- threshold/configuration version
- missing-evidence warnings

Do not directly combine unrelated uncalibrated values as if they were probabilities. Use a documented points model or explicit decision table for the MVP, for example:

- rule severity points
- statistical anomaly points
- ML-threshold crossing points
- graph-signal points
- data-sufficiency modifiers

Tune demonstration thresholds on scenario-development data and evaluate once on held-out scenarios. Keep `ml_score`, `risk_score`, and `confidence` as distinct concepts.

### Customer-level risk rollup

Customer risk is a transparent aggregation over the query's lookback window, not a second opaque model. Version `customer_rollup.v1` as:

```text
event_peak       = max(valid transaction risk scores), or 0
pattern_breadth  = min(100, sum(unique rule base_points × recency_decay))
profile_score    = bounded 0..100 profile-deviation signal, or 0 with missing-data warning
context_score    = bounded 0..100 KYC context score

recency_decay(age_days) = 0.5 ^ (age_days / 90)
composite = 0.40 × event_peak
          + 0.35 × pattern_breadth
          + 0.20 × profile_score
          + 0.05 × context_score

customer_risk_score = max(event_peak, composite)
LOW    = score < 40
MEDIUM = 40 <= score < 70
HIGH   = score >= 70
```

Rule base points, profile mappings, lookback window, the 90-day half-life, weights, and tier cutoffs are demonstration defaults stored in versioned configuration and documented in `docs/RISK_MODEL.md`. They are tuned on development scenarios and frozen before held-out evaluation. Context is deliberately capped at 5% of the composite: PEP/KYC/country context can change prioritization but cannot independently make a customer suspicious.

The rollup result records `entity_id`, lookback boundaries, contributing transaction IDs, contributing rule IDs, component scores, decay values, missing-data warnings, `rollup_method`, and policy version. A severe recent transaction may independently make the customer high risk through `event_peak`; repeated moderate patterns may reach high risk through `pattern_breadth`.

### Verification

Checks include:

- evidence reference exists
- expected scope matches actual scope
- thresholds and feature versions are recorded
- conflicting ML/rule signals are surfaced
- insufficient history lowers confidence
- an explanation cannot cite data absent from verified evidence
- high severity with weak data is queued for review rather than asserted as confirmed laundering

Verification runs before explanation. Risk may be recomputed or downgraded if evidence is invalid.

### Escalation

Deterministic policy mapping:

- `LOW` → `monitor`
- `MEDIUM` → `review`
- `HIGH` → `report`

Use wording such as “recommend preparing/escalating for reporting according to institutional policy,” not “a SAR must be filed.” Any pattern override must be documented, versioned, and configurable; a structuring rule must not automatically claim a legal reporting obligation.

`review` and `report` recommendations create or update an alert idempotently after verification succeeds. The alert stores an immutable snapshot reference rather than relying on mutable current customer data.

### Explanation

The LLM receives verified structured evidence only. It returns:

- concise finding summary
- evidence-backed reasons
- relevant numbers/windows/thresholds
- uncertainty and missing-data note
- explanation of risk level
- explanation of recommended next action
- evidence IDs for each factual claim

Use deterministic templates as a fallback when Ollama is unavailable.

### Planner and graph update

After these nodes exist, extend the planner whitelist:

- suspicious-finding paths: `risk_classification → verification → escalation → explanation`
- informational paths: omit these unless the user requests risk or suspicious results exist

### Required tests

- Risk decision-table boundary tests.
- Transaction and customer risk tests.
- Customer-rollup tests covering one severe event, repeated moderate events, recency decay, duplicate-rule suppression, profile missingness, bounded KYC context, and exact tier boundaries.
- Escalation mapping tests.
- Idempotent alert-creation tests for `review` and `report`.
- Conflicting and insufficient-evidence tests.
- Explanation citation validation.
- Hallucinated numbers/rules cause fallback or failure, not silent acceptance.
- Ollama-down path produces a deterministic explanation.

### Acceptance criteria

- Every flagged item has risk, reasons, evidence references, and escalation.
- Every explanation can be traced to verified structured evidence.
- No LLM decides authoritative risk or escalation.
- Customer risk is reproducible from the documented rollup components and versioned policy.

---

## Phase 9 — Frontend, Reports, Evaluation, and Demo Hardening

### Purpose

Make the adaptive agent behavior and its evidence understandable to a judge.

### Frontend deliverables

- Natural-language query input.
- Execution Summary panel:
  - original request
  - detected intent
  - normalized filters
  - generated plan
  - tools invoked/skipped and reasons
  - warnings/fallbacks
- Results table with transaction/customer toggle.
- Risk and escalation panel.
- Evidence and rule details.
- Explanation with evidence links.
- Reviewer alert queue sorted by risk/age, with alert history and valid actions to start review, escalate, dismiss, or close; dismissal/escalation requires a reason.
- Minimum required visualizations:
  - EDA class/scenario balance
  - amount distribution or transaction volume over time
  - suspicious-result ranking/table
- Loading, timeout, partial-result, no-data, and Ollama-unavailable states.
- JSON report export; PDF is optional.

Charts are an MVP deliverable because the problem statement requests supporting charts, tables, or metrics. Animations, graph visualization, and decorative dashboards are optional.

### Evaluation deliverables

- `docs/EVALUATION.md` with:
  - ML benchmark methodology and honest held-out metrics
  - AML scenario detection precision/recall by pattern
  - intent/filter extraction metrics
  - planner tool-selection accuracy
  - risk classification results on held-out scenarios
  - customer-rollup results on held-out scenarios
  - a same-dataset false-positive benchmark comparing the frozen naive baseline with the contextual detector
  - explanation citation/faithfulness rate
  - average latency by query type
- End-to-end tests for the six mandatory queries.
- Clean-clone setup test on the actual demo machine.
- Demo seed and pre-generated fixture small enough to run without the full raw dataset.

The false-positive comparison uses frozen, held-out AML scenario seeds that were not used to set either system's thresholds. Report at least:

| Metric | Naive fixed-threshold baseline | Contextual detector |
|---|---:|---:|
| Alerts raised | measured | measured |
| True positives | measured | measured |
| False positives | measured | measured |
| False-positive rate `FP / (FP + TN)` | measured | measured |
| Alerts per 1,000 evaluated entities | measured | measured |
| Precision | measured | measured |
| Recall | measured | measured |

Also report a contextual rules/profile-only ablation and, only for records that are genuinely ML-eligible, the incremental effect of adding ML. Do not promise a reduction in advance; report the measured result honestly. Synthetic benchmark limitations and scenario prevalence must be stated next to the table.

### Optional human-gated feedback loop

Capture reviewer dispositions (`confirmed_suspicious`, `false_positive`, `needs_more_information`) together with the immutable feature/rule/model/policy snapshot. An offline script may use accumulated labeled dispositions to propose threshold changes, but:

- it must use both positive and negative dispositions, not dismissals alone
- it must account for selection bias because reviewers only label generated alerts
- proposals are evaluated on a frozen validation set
- a human approves a new versioned policy
- the live system never self-modifies thresholds or retrains from one reviewer action

This is a stretch feature and must be cut before any mandatory Phase 8 or evaluation work. The core system's adaptivity is query-aware planning plus learned/statistical signals; online learning is not required by the minimum functional requirements.

### Demo scenarios

1. Direct amount filter: SQL only.
2. Threshold aggregation: SQL only.
3. Spending increase: Feature Engineering only.
4. Structuring search: scoped features + rules, no full EDA.
5. Single-customer investigation: entity-scoped tools, no dataset EDA.
6. Broad suspicious-activity analysis: EDA plus selected anomaly tools.

### Acceptance criteria

- UI output matches the backend execution trace exactly.
- A judge can identify why a tool ran or was skipped.
- The app degrades gracefully if the LLM is unavailable.
- A fresh clone reaches a working demo using only the README.
- The measured baseline comparison is reproducible and does not use development scenarios.
- Alert actions persist with reviewer, reason, and immutable audit history.

---

## 7. Two-Developer Work Distribution

| Phase | Developer 1 — Data/Detection | Developer 2 — Agent/API/UI | Shared gate |
|---|---|---|---|
| 0 | Data/model contracts | API/agent contracts | Contract-v1 and CI pass |
| 1 | DB, customer profiles, generator, ML training/evaluation | schemas, seed tooling review | reproducible data + model |
| 2 | features, rules, and naive benchmark | query-scope integration, tests | hand-calculated fixtures pass |
| 3 | anomaly/feature/SQL tools | EDA, API, tool registry, alert API | deterministic tool API works |
| 4 | worker-node adapters | state graph and tracing | plan-specific execution works |
| 5 | labeled queries and evaluation | intent parser/router | extraction targets met |
| 6 | validator and templates | planner prompt/integration | tool-selection tests pass |
| 7 | relationship graph | retrieval | optional; cut together if needed |
| 8 | risk, customer rollup, verification, escalation | explanation and graph integration | full flagged result is grounded |
| 9 | evaluation/baseline/report export | frontend and reviewer queue | clean-clone demo passes |

Both developers review schema changes. Contract changes require versioning rather than silent edits.

---

## 8. Six-Week Schedule and Gates

### Week 1 — Foundation and data

- Phase 0 and most of Phase 1.
- Gate: raw data is immutable, versioned customer profiles and AML scenarios are reproducible, corrected ML split/training path runs.

### Week 2 — Deterministic detection core

- Finish Phase 1, complete Phase 2, start Phase 3.
- Gate: direct SQL, customer-profile features, rules, statistics, ML, and the evaluation-only naive baseline can be independently tested.

### Week 3 — Tool API and workflow

- Finish Phase 3 and Phase 4.
- Gate: two different explicit plans produce different tool traces; no fixed final pipeline remains.

### Week 4 — Natural-language agent

- Phase 5 and Phase 6.
- Gate: mandatory queries extract correct filters and select correct tools.

### Week 5 — Risk and explanation

- Phase 8 is mandatory.
- Phase 7 proceeds only if all core gates pass.
- Gate: held-out scenarios produce verified transaction/customer risk, alert creation, escalation, and grounded explanation.

### Week 6 — Productization and evaluation

- Phase 9.
- Freeze new features at least three days before presentation.
- Gate: false-positive comparison, alert queue, clean-clone test, and rehearsed live demo pass.

---

## 9. Testing and Evaluation Matrix

| Layer | Required evidence |
|---|---|
| Data | schema checks, referential integrity, effective-dated customer profiles, scenario reproducibility, no ground-truth leakage |
| ML | leakage-safe splits, validation threshold, untouched test metrics, preprocessing parity |
| Features | hand-calculated unit fixtures, window/boundary/filter tests |
| Rules | positive, negative, exact-threshold, insufficient-data cases |
| EDA | known fixture summaries and chart-schema snapshots |
| Intent | per-field extraction accuracy on labeled queries |
| Planner | tool-selection precision/recall and invalid-plan rejection |
| Workflow | invoked/skipped trace, timeout, partial failure, no duplicate execution |
| Risk | decision boundaries, customer rollup/recency, held-out scenario classification |
| Explanation | evidence citation coverage, unsupported-claim rejection |
| Alerts | idempotent creation, valid transitions, immutable audit history, disposition reason |
| Baseline comparison | frozen thresholds/seeds, false-positive rate, alerts per 1,000, contextual ablations |
| API/UI | contract tests, alert queue/actions, and six mandatory end-to-end queries |

CI should use tiny committed fixtures. Full raw-data and model evaluation runs separately because large datasets and model artifacts should not be committed.

---

## 10. Major Risks and Mitigations

| Risk | Impact | Required mitigation |
|---|---|---|
| Treating card fraud as AML ground truth | Invalid project claims | separate ML benchmark and AML scenario evaluation |
| Synthetic scenarios leak labels | Artificially perfect rules | hide manifests from runtime; test module boundaries |
| Imported model preprocessing mismatch | Silently wrong scores | retrain first-party pipeline; schema/version checks |
| Biased threshold evaluation | Inflated metrics | validation-only selection; untouched test |
| Fixed pipeline hidden behind LangGraph | Fails core brief | plan-driven nodes and asserted skipped-tool traces |
| Feature tool not orchestrated | Feature-only queries break | first-class worker, node, registry entry, and planner operation |
| LLM malformed output | Pipeline failure | schema-constrained output, validation, retry, deterministic fallback |
| LLM unavailable during demo | No response | deterministic route/plan/explanation fallbacks |
| Hardcoded legal thresholds | Misleading and brittle | configurable policy by jurisdiction/currency |
| Customer context becomes automatic suspicion | Discriminatory or misleading results | contextual attributes are bounded, never standalone rule triggers, with missingness/provenance |
| Synthetic benchmark is tuned to favor the hybrid | Unsupported false-positive claim | frozen held-out seeds, thresholds selected on development only, ablations and limitations reported |
| Risk score conflated with ML score | Unexplainable output | separate signal, risk, and confidence contracts |
| Duplicate alerts or unaudited reviewer actions | Broken compliance workflow | idempotency key, transition state machine, append-only audit events |
| Feedback loop learns from biased/noisy dismissals | Threshold degradation | collect full dispositions, offline evaluation, human approval, policy versioning |
| Explanation hallucination | Loss of trust | verified evidence only, evidence IDs, automated claim checks |
| Neo4j/Chroma delays | Core work unfinished | cut Phase 7 before reducing Phase 8 |
| Missing upstream license | Attribution/legal issue | reference only; independently implement; document attribution |

---

## 11. MVP Scope

### Mandatory

- Phases 0–6, 8, and 9.
- Correct first-party ML baseline or an explicitly disabled ML tool if model validation is unfinished.
- Selective EDA.
- First-class Feature Engineering Tool.
- Anomaly Detection Tool supporting at least rules and one ML/statistical path.
- Transaction and customer risk.
- Versioned customer-risk rollup using transaction, pattern, profile, and bounded KYC context.
- Verification, escalation, grounded explanation.
- Alert queue, reviewer actions, and immutable transition history.
- Accurate execution summary.
- Results table and minimal supporting charts.
- Reproducible naive-baseline versus contextual-detector comparison.
- Automated tests for all mandatory queries.

### Optional

- Neo4j.
- ChromaDB.
- SHAP.
- calibrated probability.
- parallel graph execution.
- PDF export.
- graph visualization.
- offline human-gated feedback/calibration.

### Never fake

- Retrieved documents.
- graph relationships.
- model metrics.
- calibrated probabilities.
- legal reporting obligations.
- tools listed as invoked when they did not run.
- guaranteed false-positive reduction before measurement.

If a capability is unavailable, report it as skipped/unavailable with a reason.

---

## 12. Final Deliverable Checklist

- [ ] Root repository, environment, CI, README, and health endpoint.
- [ ] Architecture, roadmap, data dictionary, model card, evaluation, and attribution docs.
- [ ] Immutable raw ULB data and reproducible split manifest.
- [ ] Independent, leakage-safe ML training/inference pipeline.
- [ ] Deterministic AML scenario generator with hidden evaluation labels.
- [ ] Customer profiles plus account, transaction, counterparty, and device schema, with effective dates and missing-data handling.
- [ ] Query scoping applied before tool execution.
- [ ] Feature Engineering Tool independently callable.
- [ ] Rules consume shared features and configurable thresholds.
- [ ] Profile-deviation features/rule are tested; PEP/KYC context cannot independently trigger suspicion.
- [ ] Evaluation-only naive fixed-threshold baseline is frozen before held-out testing.
- [ ] EDA Tool returns real metrics and chart data.
- [ ] Anomaly Detection Tool selects rules/statistics/ML/hybrid by plan.
- [ ] Transaction-level risk and documented, versioned customer-level risk rollup.
- [ ] Intent parser extracts all required filters and entities.
- [ ] Router and planner produce minimal validated plans.
- [ ] State graph executes only planned nodes.
- [ ] Execution trace records invoked/skipped tools and reasons.
- [ ] Verification runs before explanation.
- [ ] Escalation deterministically maps verified risk to action.
- [ ] Review/report outcomes create idempotent alerts with immutable evidence snapshots.
- [ ] Explanations cite verified evidence and have a deterministic fallback.
- [ ] Final API exposes execution summary, results, evidence, charts, and answer.
- [ ] Frontend visibly demonstrates adaptive tool selection.
- [ ] Reviewer queue supports valid, audited alert dispositions.
- [ ] Held-out baseline comparison reports measured false positives, precision, recall, and limitations.
- [ ] Mandatory query suite and clean-clone demo pass.
- [ ] Optional feedback loop is either human-gated and evaluated or explicitly documented as deferred.
- [ ] All third-party assets are attributed and license limitations documented.

---

## 13. Known Scope Limits and Decisions Still Required

The challenge requirements are covered, but the following items cannot be honestly marked “resolved” by a roadmap alone:

1. **Final architecture source:** `docs/ARCHITECTURE.md` is not yet present in the workspace. Before implementation, persist the finalized Part 10 architecture and create a short requirements-to-components traceability matrix. This roadmap should be corrected if that source contains a conflicting contract.
2. **Policy and domain validation:** rollup weights, scenario definitions, rule thresholds, high-risk-country data, and escalation mappings are demonstration defaults. A qualified AML/compliance reviewer must validate them before any real-world claim.
3. **Synthetic benchmark limits:** the false-positive comparison can support a hackathon result only on the declared synthetic distribution. It cannot establish production false-positive reduction without representative institutional data and analyst dispositions.
4. **Dataset onboarding:** the MVP assumes versioned, preloaded schemas. Arbitrary CSV upload, schema mapping, malware scanning, column-level validation, and asynchronous ingestion are not included. Add a dataset-onboarding phase if judges must upload unseen files.
5. **Multi-currency normalization:** either constrain the demo to one currency or freeze a dated synthetic FX-rate table. Do not compare or aggregate amounts across currencies without an explicit conversion source and rate timestamp.
6. **Production security and privacy:** real authentication, RBAC, encryption/key management, PII masking, retention/deletion policy, consent, backup/restore, and regulatory audit controls are outside the hackathon MVP. Only synthetic data should be exposed in the demo.
7. **Operational monitoring:** production drift detection, model/data-quality monitoring, alert-volume monitoring, service-level objectives, and retraining cadence are not implemented. Phase 9 measures demo latency and quality but is not a production observability program.
8. **Fairness and sensitivity:** because KYC/country/profile context can affect prioritization, evaluate whether the bounded context component disproportionately changes outcomes across synthetic segments. This does not replace legal/compliance review and must not be presented as proof of fairness.
9. **Scale limits:** SQLite and local Ollama are appropriate for the MVP, not concurrent institutional workloads. Record the tested dataset size, hardware, p50/p95 latency, and maximum result limits so the demonstrated capacity is explicit.

These are not blockers for the stated synthetic hackathon MVP unless arbitrary dataset upload is part of the judging flow. They are blockers for describing the system as production-ready or suitable for real customer data.

---

## 14. Definition of Done

The platform is complete when a judge can submit each mandatory query and observe a different, appropriate execution path; inspect the exact filters and tools selected; review transaction/customer findings with evidence-backed risk and escalation; act on an alert through an audited lifecycle; and verify that broad EDA, customer/profile analysis, feature computation, rules, statistical checks, and ML are invoked only when relevant. The evaluation must also show the measured false-positive trade-off against the frozen naive baseline on held-out scenarios.

The project must be described accurately: a query-aware hybrid suspicious-activity investigation prototype using a supervised card-fraud model as one optional signal and synthetic AML scenarios for typology evaluation. It must not be presented as a production AML system, a legal reporting engine, or a model trained directly to recognize structuring unless the corresponding labeled data and evaluation genuinely support that claim.
