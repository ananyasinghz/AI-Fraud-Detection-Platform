# AI-Powered Suspicious Activity Detection Platform

## Part 10 — Final Recommended Enterprise AI Architecture, Revision 2

**Status:** Authoritative implementation architecture  
**Contract version:** `v1`  
**Last reconciled:** 2026-07-26

This workspace document records the implementation-relevant form of the user-supplied “Part 10 — Final Recommended Enterprise AI Architecture (Implementation Blueprint), Revision 2.” The strict Phase 0 contracts remain authoritative where the document's abbreviated JSON examples omitted safety fields: raw `AnalysisRequest` and parsed intent remain separate, plan dependencies use unique step IDs, and tool results retain operation, timestamp, evidence, error, and provenance fields. The required execution `route` is part of contract `v1`.

## Architectural Principles

1. **Deterministic first:** SQL, feature calculations, rules, risk classification, verification, and escalation remain deterministic and auditable.
2. **LLM at the edge:** an LLM may extract intent, propose a validated plan, and explain verified evidence. It may not calculate authoritative AML metrics or choose risk/escalation outcomes.
3. **Query-aware execution:** each request produces a minimal plan. The system must not hide a fixed SQL → Rules → ML pipeline behind an agent interface.
4. **Evidence before explanation:** explanations consume verified structured evidence and cite evidence identifiers.
5. **Explicit scope:** every tool receives normalized filters, entity scope, time boundaries, and limits.
6. **Graceful degradation:** deterministic routes and templates remain usable when the local LLM is unavailable.
7. **Honest evaluation:** card-fraud benchmarking and synthetic AML-typology evaluation are separate tracks.

Every natural-language query normally uses one small intent-parsing LLM call. “SQL-only” and “feature-only” mean zero additional planning/explanation LLM calls and zero LLM involvement in the numerical decision, not literally zero total calls. Deterministic parsing templates provide the no-LLM fallback.

## Logical Layers

```text
User/API
  │
  ▼
Intent Extraction
  │
  ▼
Date/Filter Normalization → Query Scope Resolver
  │
  ▼
Deterministic Three-Way Router
  ├── Simple SQL ───────────────────────────────────────────────┐
  ├── Feature-Only ─────────────────────────────────────────────┤
  └── Complex → Planner + Plan Validator                        │
                              │                                  │
                              ▼                                  │
                    Investigation State Graph                    │
  ├── Targeted SQL Tool
  ├── EDA Tool
  ├── Feature Engineering Tool
  ├── Anomaly Detection Tool
  │     ├── deterministic rules
  │     ├── robust statistics
  │     └── optional supervised ML scorer
  ├── Graph Analysis Tool (optional)
  └── Retrieval Tool (optional)
                              │                                  │
                              ▼                                  │
                    Evidence Aggregation                         │
                              │                                  │
                              ▼                                  │
                    Evidence Verification                        │
                              │                                  │
                              ▼                                  │
                    Risk Classification                          │
                              │                                  │
                              ▼                                  │
                    Risk Consistency Check                       │
                              │                                  │
                              ▼                                  │
                    Escalation → Grounded Explanation             │
                              │                                  │
                              └──────────────────────────────────┤
                                                                 ▼
                         Execution Summary + Results + Charts + Alerts
```

## Required Capabilities

### EDA Tool

Profiles transaction and synthetic customer data for broad requests. It reports data quality, distributions, volume over time, customer-profile completeness, and chart specifications. Targeted entity requests skip it.

### Feature Engineering Tool

Computes only requested, scoped AML features such as rolling sums/counts, velocity, baseline deviation, rapid cash-out, profile deviation, and distinct relationship counts. Feature-only questions can return directly without anomaly detection.

### Anomaly Detection Tool

Selects rules-only, statistical-only, ML-only, or hybrid operations according to a validated plan. It returns signals and evidence, not the final risk tier.

### Risk Classification Tool

Converts verified signals into transaction or customer risk using versioned deterministic policy. ML score, risk score, and confidence are separate concepts.

### Explanation Component

Produces concise natural-language explanations from verified evidence only. Deterministic templates provide a fallback.

## Supporting Components

- **Targeted SQL Tool:** direct lookup, filtering, and threshold aggregation.
- **Router:** deterministic three-way mapping to SQL-only, feature-only, or full investigation.
- **Planner:** proposes tool steps for non-template requests.
- **Plan Validator:** enforces the tool whitelist, schemas, dependencies, scope, and limits.
- **State Graph:** executes validated steps and records invoked/skipped tools, timing, failures, and fallbacks.
- **Evidence Aggregator:** merges typed tool results without inventing conclusions.
- **Evidence Verification:** validates scope, provenance, versions, references, structure, and sufficiency before risk calculation.
- **Risk Consistency Verification:** independently reproduces/checks risk inputs, weights, caps, tiers, conflicts, and confidence before escalation.
- **Escalation:** maps verified risk to monitor/review/report recommendations.
- **Alert Lifecycle:** persists review/report outcomes with idempotent creation and append-only transitions.
- **Graph Analysis:** NetworkX MVP over scoped SQL relationships (shared device, cycles, two-hop).
- **Policy Retrieval:** Chroma/local HashingVectorizer index over committed illustrative excerpts; context only.

## Data Boundaries

Two datasets serve different purposes:

1. The immutable ULB/Kaggle credit-card dataset supports supervised transaction-fraud benchmarking only.
2. Reproducible synthetic customer/account scenarios support AML feature, rule, routing, risk, and false-positive evaluation.

The runtime cannot access hidden scenario labels. Synthetic transactions without the ML feature schema are marked ineligible and cause a recorded ML skip.

The imported third-party fraud repository is reference material only. Runtime code must not import from it, and its unlicensed source/model artifacts must not be redistributed without permission.

## Contract Boundaries

All inter-component messages use strict Pydantic `v1` contracts:

- analysis request and normalized filters
- parsed intent
- validated plan and plan steps
- tool result envelope
- evidence reference and evidence bundle
- execution summary
- chart specification
- flagged result
- final response

Every execution summary records an explicit `simple_lookup`, `feature_only`, or `full_investigation` route. Every result records scope, status, warnings, timing, and provenance. Informational SQL/feature responses may omit risk and escalation when no suspicious finding was requested or produced.

## Requirement Traceability

| Challenge requirement | Owning component |
|---|---|
| Parse intent, filters, entities, and AML pattern | Intent Extraction + Router |
| Build a dynamic execution plan | Planner + Plan Validator |
| Query-scoped loading/preprocessing | Query Scope + tool adapters |
| Selective EDA | EDA Tool + validated plan |
| On-demand AML features | Feature Engineering Tool |
| Rule/statistical/ML/hybrid detection | Anomaly Detection Tool |
| Transaction/customer risk | Risk Classification Tool |
| Valid evidence before risk | Evidence Verification |
| Reproducible risk before action | Risk Consistency Verification |
| Human-readable reasons | Explanation Component over doubly verified evidence |
| Monitor/review/report | Escalation + Alert Lifecycle |
| Inspectable agent decisions | State Graph execution trace |
| Charts, tables, and metrics | EDA Tool + final response/frontend |
| Live demo UI matching backend traces | React views ← enriched QueryResponse |

## Security and Safety Boundaries

- The hackathon demo uses synthetic customer data only.
- LLM output never becomes executable code or raw SQL.
- Unknown tools, operations, fields, and invalid plans are rejected.
- Amount thresholds are versioned by currency/jurisdiction and are not legal advice.
- PEP, country, occupation, or KYC context cannot independently assert suspicious activity.
- Real authentication, RBAC, encryption, retention, and production regulatory controls remain outside the MVP.

## Deployment Baseline

The MVP is a local monorepo:

- Python 3.11 and FastAPI backend
- SQLite data store
- local Ollama model for optional NLU/planning/explanation
- React frontend (Phase 9) against live `/api/v1` with Vite proxy / CORS
- optional Neo4j and ChromaDB extensions

This baseline is suitable for a synthetic hackathon demonstration, not institutional production workloads.

## Phase 8 runtime notes

Implemented packages: `backend/app/evidence/`, `backend/app/risk/`, `backend/app/explanation/`,
wired through `backend/app/tools/phase8.py` and the tool registry. Policy defaults live in
`config/policy/risk_scoring.v1.yaml` and `docs/RISK_MODEL.md`. Aggregate responses may include
`FlaggedResult` items after dual-gate verification; SQL/feature-only plans omit the Phase 8 chain.

## Phase 9 demo notes

`QueryResponse` / investigation payloads copy `results`, `charts`, and `supporting_evidence`
from workflow `FinalResponse`. `GET /customers` lists sparse directory rows. CORS allows Vite
origins. Demo default is Ollama off (`FRAUD_OLLAMA_ENABLED=false`). Frontend client:
`frontend/src/services/api.ts`.

## Reconciliation Result

This architecture and `IMPLEMENTATION_ROADMAP.md` agree on:

- deterministic-first, LLM-at-the-edge behavior
- five first-class challenge capabilities
- first-class feature engineering and anomaly detection
- explicit three-way routing recorded in every execution summary
- transaction/customer risk and customer rollup
- pre-risk evidence verification and post-risk consistency verification
- doubly verified explanations and deterministic escalation
- query-aware invoked/skipped tool tracing
- separate ML and AML evaluation tracks
- alert lifecycle and honest false-positive benchmarking
- demo frontend wired to live APIs

The architecture's JSON snippets are explanatory, not permission to weaken the strict Phase 0 schemas. Raw requests do not contain model-detected intent, and plan dependencies refer to unique `step_id` values rather than ambiguous tool names. No Phase 0 contract may introduce Phase 1 business logic. Future architecture changes require an explicit version and corresponding contract/test updates.
