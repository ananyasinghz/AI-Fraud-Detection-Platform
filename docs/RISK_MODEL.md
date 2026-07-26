# Risk Model

**Status:** Phase 8 — demonstration defaults (`risk_scoring.v1` / `customer_rollup.v1`)

This document freezes the hackathon risk policy. It is **not legal advice**, **not a calibrated
probability model**, and **not** a substitute for institutional SAR/STR decisioning. Thresholds
are tuned on development scenarios and frozen before held-out evaluation.

Config source: [`config/policy/risk_scoring.v1.yaml`](../config/policy/risk_scoring.v1.yaml).

## Distinct score concepts

| Field | Range | Meaning |
| --- | --- | --- |
| `ml_score` | model-native (often 0–1) | Raw ML tool signal only |
| `risk_score` | 0–100 | Points/rollup outcome after policy |
| `confidence` | 0–1 | Evidence sufficiency / conflict posture |
| `risk_level` | LOW / MEDIUM / HIGH | Tier from `risk_score` cutoffs |
| `escalation_action` | monitor / review / report | Deterministic map from tier |

Never treat `ml_score` as `risk_score`. Never let an LLM set authoritative risk or escalation.

## Tier cutoffs

- **LOW:** `risk_score < 40`
- **MEDIUM:** `40 <= risk_score < 70`
- **HIGH:** `risk_score >= 70`

## Transaction points model

Additive points (capped to `[0, 100]`):

| Signal | Demo points |
| --- | ---: |
| Rule severity low / medium / high / critical | 15 / 35 / 55 / 75 |
| Statistical anomaly | 20 |
| ML threshold cross (`ml_score >= 0.5`) | 25 |
| Graph shared device | 20 |
| Graph circular transfer | 30 |
| Graph two-hop exposure | 15 |

Data-sufficiency: subtract 15 points and cap confidence at 0.45 when insufficient history is
flagged. Full-signal confidence defaults to 0.85; reduced/no-signal confidence defaults to 0.55.

## Customer rollup (`customer_rollup.v1`)

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
```

Rule base points for pattern breadth: low 10 / medium 20 / high 35 / critical 50. Duplicate rule
IDs keep the maximum contribution only. Lookback half-life is 90 days.

**Context bound:** KYC/PEP/country context is capped at 5% of the composite and **cannot alone**
force a MEDIUM/HIGH tier.

## Dual-gate verification

1. **Stage 1 (`verify_evidence`)** — resolve evidence refs, scope match, versions, structure,
   sufficiency; block risk when required evidence fails.
2. **Stage 2 (`verify_risk_consistency`)** — reproduce tier from policy, validate rollup weights,
   reject/downgrade context-only or weak-data HIGH results.

Only dual-verified risk may escalate or explain.

## Escalation map

| Risk level | Action | Alert |
| --- | --- | --- |
| LOW | `monitor` | no |
| MEDIUM | `review` | idempotent create |
| HIGH | `report` | idempotent create |

Wording recommends preparing/escalating for reporting **according to institutional policy**.
Never assert “a SAR must be filed.”

Manual alert-create APIs may still map request severity through
`provisional_risk_from_severity` until a verified Phase 8 payload is attached. Investigation-driven
alerts overlay verified `risk_score` / tier / escalation from the dual-gate result.

## Explanation

Ollama is optional (`FRAUD_OLLAMA_*` / settings). One retry; deterministic template fallback when
disabled or failed. Citation checks reject hallucinated evidence IDs / rule tokens; failures fall
back or fail closed — never silently accept invented facts.
