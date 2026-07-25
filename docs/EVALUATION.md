# Evaluation

**Status:** Phase 1 data/ML evaluation complete; later-system measures pending

## Phase 1 Verification

The fixture suite covers migrations, foreign keys and indexes, profile as-of resolution, interval overlap rejection, missing-profile warnings, seed idempotency, scenario reproducibility, hidden-label boundaries, immutable ULB validation, duplicate-group isolation, preprocessing parity, validation-only thresholding, artifact reload, strict schema failures, and batch/single scorer parity.

Current result: 46 tests passed with 94.99% branch-aware coverage. Ruff and strict mypy pass.

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

The generated catalog includes clean controls and nine injected scenario families. These are test inputs with hidden expected signals, not measured detection results. Phase 1 contains no feature/rule engine, so reporting pattern precision/recall now would be false.

## Pending for Later Phases

- synthetic scenario detection results by pattern
- intent/filter extraction and planner tool-selection accuracy
- transaction and customer risk results
- naive baseline versus contextual detector false-positive comparison
- explanation citation/faithfulness
- p50/p95 end-to-end latency

Development and held-out scenario populations remain separate. No expected result is presented as a measured detector result.
