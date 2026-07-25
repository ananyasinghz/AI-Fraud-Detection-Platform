# Risk Model

**Status:** Placeholder — implemented in Phase 8

Phase 0 reserves separate concepts for:

- tool/model signal
- normalized risk score (`0..100`)
- risk level (`LOW`, `MEDIUM`, `HIGH`)
- confidence (`0..1`)
- escalation action (`monitor`, `review`, `report`)

Phase 8 must version and document transaction scoring, customer rollup, recency decay, component weights, data-sufficiency handling, tier boundaries, escalation mapping, and held-out evaluation. PEP, country, occupation, or KYC context must remain bounded and cannot independently assert suspicious activity.
