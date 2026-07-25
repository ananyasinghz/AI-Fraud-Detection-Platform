# AI-Powered Suspicious Activity Detection Platform

## Architecture Baseline

**Status:** Phase 0 architecture baseline  
**Contract version:** `v1`  
**Last reconciled:** 2026-07-25

The original “Part 10 — Final Recommended Enterprise AI Architecture” was referenced in planning but was not supplied as a workspace file when Phase 0 began. This document therefore records the architecture that is verifiably supported by the corrected implementation roadmap. It is not represented as a verbatim copy of the missing source. If that source is supplied later, it must be compared against this file and conflicts resolved through a versioned architecture decision.

## Architectural Principles

1. **Deterministic first:** SQL, feature calculations, rules, risk classification, verification, and escalation remain deterministic and auditable.
2. **LLM at the edge:** an LLM may extract intent, propose a validated plan, and explain verified evidence. It may not calculate authoritative AML metrics or choose risk/escalation outcomes.
3. **Query-aware execution:** each request produces a minimal plan. The system must not hide a fixed SQL → Rules → ML pipeline behind an agent interface.
4. **Evidence before explanation:** explanations consume verified structured evidence and cite evidence identifiers.
5. **Explicit scope:** every tool receives normalized filters, entity scope, time boundaries, and limits.
6. **Graceful degradation:** deterministic routes and templates remain usable when the local LLM is unavailable.
7. **Honest evaluation:** card-fraud benchmarking and synthetic AML-typology evaluation are separate tracks.

## Logical Layers

```text
User/API
  │
  ▼
Intent Extraction ──► Deterministic Router
  │                         │
  │ direct template        │ complex request
  ▼                         ▼
Validated Plan ◄──── Planner + Plan Validator
  │
  ▼
Investigation State Graph
  ├── Targeted SQL Tool
  ├── EDA Tool
  ├── Feature Engineering Tool
  ├── Anomaly Detection Tool
  │     ├── deterministic rules
  │     ├── robust statistics
  │     └── optional supervised ML scorer
  ├── Graph Analysis Tool (optional)
  └── Retrieval Tool (optional)
  │
  ▼
Evidence Aggregation
  │
  ▼
Risk Classification → Verification → Escalation
  │
  ▼
Grounded Explanation
  │
  ▼
Execution Summary + Findings + Evidence + Charts + Alert
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
- **Router:** deterministic mapping for common/simple intents.
- **Planner:** proposes tool steps for non-template requests.
- **Plan Validator:** enforces the tool whitelist, schemas, dependencies, scope, and limits.
- **State Graph:** executes validated steps and records invoked/skipped tools, timing, failures, and fallbacks.
- **Evidence Aggregator:** merges typed tool results without inventing conclusions.
- **Verification:** validates scope, provenance, versions, evidence references, conflicts, and sufficiency.
- **Escalation:** maps verified risk to monitor/review/report recommendations.
- **Alert Lifecycle:** persists review/report outcomes with idempotent creation and append-only transitions.
- **Graph/Policy Retrieval:** optional extensions, never fabricated when unavailable.

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

Every result records scope, status, warnings, timing, and provenance. Informational SQL/feature responses may omit risk and escalation when no suspicious finding was requested or produced.

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
| Human-readable reasons | Verification + Explanation Component |
| Monitor/review/report | Escalation + Alert Lifecycle |
| Inspectable agent decisions | State Graph execution trace |
| Charts, tables, and metrics | EDA Tool + final response/frontend |

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
- React frontend in a later phase
- optional Neo4j and ChromaDB extensions

This baseline is suitable for a synthetic hackathon demonstration, not institutional production workloads.

## Reconciliation Result

This architecture and `IMPLEMENTATION_ROADMAP.md` agree on:

- deterministic-first, LLM-at-the-edge behavior
- five first-class challenge capabilities
- first-class feature engineering and anomaly detection
- transaction/customer risk and customer rollup
- verified explanations and deterministic escalation
- query-aware invoked/skipped tool tracing
- separate ML and AML evaluation tracks
- alert lifecycle and honest false-positive benchmarking

No Phase 0 contract may introduce Phase 1 business logic. Future architecture changes require an explicit version and corresponding contract/test updates.
