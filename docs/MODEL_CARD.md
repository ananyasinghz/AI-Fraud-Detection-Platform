# Model Card — ULB Fraud Scorer v1

**Status:** Phase 1 measured baseline  
**Selected artifact:** `ulb.random_forest.v1`  
**Preprocessing:** `preprocessing.v1`

## Intended Use

This model ranks transactions that already have the exact anonymized ULB schema for card-fraud investigation support. It is one future input to a wider investigation and never makes an AML filing, customer-risk, account-blocking, or adverse-action decision by itself.

Prohibited claims:

- It does not detect AML typologies.
- It does not score the synthetic AML transaction schema.
- `ml_score` is not a calibrated probability.
- The held-out metrics do not establish production performance, fairness, or regulatory fitness.
- It must not be used with missing, extra, reordered, or reconstructed ULB features.

## Data and Split

Source: the Kaggle/ULB `creditcard.csv`, 284,807 rows and 492 fraud labels. Pinned SHA256:

`76274b691b16a6c49d3f159c883398e03ccd6d1ee12d9d8ee38f4b4b98551a89`

All 30 non-label columns are grouped before splitting, so exact duplicate features cannot cross partitions. Seed `42` produced:

| Partition | Rows | Fraud rows |
|---|---:|---:|
| Train | 199,407 | 347 |
| Validation | 42,705 | 71 |
| Test | 42,695 | 74 |

There are 283,726 feature groups and 1,081 duplicate rows. Assignment SHA256:

`ec4c1505cb74e61c7bcb99d922c48cac153aaafb6f6c1065b8037c7befd55b44`

Test labels were isolated during training and opened only by the offline evaluation module after model and threshold freeze.

## Features and Preprocessing

Input order is exactly `Time`, `V1`–`V28`, `Amount`. `Time` is dropped; `Amount` becomes `log1p_Amount`; `V1`–`V28` pass through. A standard scaler is fitted on training rows only. The resulting fixed order is `V1`–`V28`, `log1p_Amount`.

## Candidates and Selection

First-party code trained:

- class-weighted logistic regression baseline
- class-weighted Random Forest candidate (200 trees, fixed seed)

No resampling, engineered `V17_V14`, model, or reported metric was copied from the unlicensed reference repository.

Thresholds maximize validation F1 subject to recall at least `0.80`, with ties resolved by highest F1, recall, then threshold. Candidate selection uses validation PR-AUC first, then validation F1. Random Forest was selected on validation PR-AUC `0.737878` versus logistic regression `0.618757`; test labels did not influence selection.

## Frozen Test Results

| Model | Threshold | PR-AUC | ROC-AUC | Precision | Recall | F1 | Alert rate | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Logistic regression | 0.804198 | 0.761853 | 0.984458 | 0.191977 | 0.905405 | 0.316785 | 0.008174 | 42,339 / 282 / 7 / 67 |
| Random Forest | 0.009775 | 0.891986 | 0.990645 | 0.062009 | 0.959459 | 0.116489 | 0.026818 | 41,547 / 1,074 / 3 / 71 |

The selected Random Forest has better ranking quality and recall but a materially worse operating-point precision/F1 than logistic regression under the fixed recall-floor policy. This is an explicit false-positive trade-off, not a hidden success claim. Later policy work should compare operating points without tuning on test data.

Brier values (`0.022058` logistic; `0.000399` Random Forest) are diagnostics only. No calibration method or calibration claim is applied.

## Limitations

- ULB features are anonymized and dataset-specific; feature semantics and subgroup attributes are unavailable.
- No demographic/fairness subgroup evaluation is possible from this dataset.
- Fraud prevalence, drift, acquisition channel, geography, and costs may differ in deployment.
- Duplicate grouping blocks exact-row leakage but cannot prove absence of related-card or temporal leakage because entity IDs are unavailable.
- Thresholds optimize a generic recall-floor/F1 recipe, not reviewed business costs.
- Synthetic AML scenarios are a separate track and provide no evidence for this model's fraud accuracy.

Generated artifacts and metrics are gitignored. Their metadata records Python 3.11.4, NumPy 2.4.6, pandas 3.0.5, scikit-learn 1.9.0, and joblib 1.5.3.
