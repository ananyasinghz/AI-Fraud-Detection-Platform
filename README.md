# Suspicious Activity Detection Platform

Query-aware, deterministic-first AML investigation prototype for a hackathon/research MVP.

Phase 1 implements the versioned SQLite foundation, deterministic synthetic AML scenarios, and a first-party leakage-safe ULB fraud scorer. Detection rules, orchestration, risk logic, and the frontend remain later phases described in [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md).

## Requirements

- Python 3.11
- Git
- Windows PowerShell, macOS, or Linux shell

Full local ML preparation expects `dataset/creditcard.csv`. The imported `Fraud Detection/` repository is reference-only, has no supplied license, and is never imported at runtime.

## Setup

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

### macOS/Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

## Phase 1 Workflow

Run from the repository root. Generated data, SQLite files, hidden labels, and model artifacts are gitignored.

```powershell
python scripts/verify_environment.py
alembic upgrade head

python scripts/generate_aml_scenarios.py --seed 42 --split dev --dry-run --verbose
python scripts/generate_aml_scenarios.py --seed 42 --split dev --verbose
python scripts/seed_database.py --seed 42 --split dev --verbose

python scripts/prepare_ml_data.py
python scripts/train_ml_models.py
python scripts/evaluate_ml_models.py
python scripts/verify_ml_environment.py
```

Re-running generation produces the same fingerprint. Re-running seeding returns `"created": false` and does not duplicate rows. Seed `99` with `--split held_out` creates the isolated held-out AML population.

Inspect outputs:

| Output | Location |
|---|---|
| SQLite database | `data/processed/fraud.db` |
| Runtime AML bundle | `data/generated/dev/seed-42/runtime_bundle.json` |
| Hidden offline manifest | `data/evaluation/dev/seed-42.json` |
| ULB split manifest | `data/splits/ulb_split.v1/manifest.json` |
| Selected model metadata | `models/ulb_v1/selected/metadata.json` |
| Frozen test metrics | `data/evaluation/ml/test_metrics.v1.json` |

Example SQLite inspection:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/processed/fraud.db'); print(c.execute('select run_id, source_fingerprint, record_counts from dataset_runs').fetchall()); print(c.execute('select count(*) from transactions').fetchone())"
```

The model API is `backend.app.ml.fraud_scorer.FraudScorer`. It requires exactly ordered `Time`, `V1`–`V28`, `Amount` fields; missing, extra, or reordered input fails loudly. `ml_score` is a ranking score, not a calibrated probability.

## Run the API

```bash
uvicorn backend.app.main:app --reload
```

Health check:

```text
GET http://127.0.0.1:8000/api/v1/health
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

## Quality Checks

```bash
ruff format --check .
ruff check .
mypy backend
pytest
```

Apply formatting with:

```bash
ruff format .
```

## Environment Variables

All application variables use the `FRAUD_` prefix. Copy `.env.example` to `.env` for local use. Never commit `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `FRAUD_APP_NAME` | `Suspicious Activity Detection API` | Service display name |
| `FRAUD_APP_VERSION` | `0.1.0` | Service version |
| `FRAUD_ENVIRONMENT` | `development` | `development`, `test`, or `production` |
| `FRAUD_DEBUG` | `false` | Framework debug behavior |
| `FRAUD_LOG_LEVEL` | `INFO` | Python logging level |
| `FRAUD_API_PREFIX` | `/api/v1` | Versioned API prefix |
| `FRAUD_DATABASE_URL` | `sqlite:///./data/processed/fraud.db` | SQLAlchemy database URL |
| `FRAUD_DATA_DIR` | `data` | Generated data root |
| `FRAUD_MODEL_DIR` | `models` | Model artifact root |
| `FRAUD_POLICY_CONFIG_PATH` | `config/policy/reporting_thresholds.v1.yaml` | Illustrative USD policy |
| `FRAUD_SCENARIO_CONFIG_PATH` | `config/generation/scenario_catalog.v1.yaml` | Scenario catalog |
| `FRAUD_RAW_CREDITCARD_PATH` | `dataset/creditcard.csv` | Local ULB source |
| `FRAUD_DEVELOPMENT_SEED` | `42` | Development generation seed |
| `FRAUD_HELDOUT_SEED` | `99` | Held-out generation seed |
| `FRAUD_ML_ENABLED` | `true` | ML capability flag |
| `FRAUD_ML_MODEL_DIR` | `models/ulb_v1/selected` | Selected scorer artifact |

## Project Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md)
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md)
- [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md)
- [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md)
- [`docs/EVALUATION.md`](docs/EVALUATION.md)
- [`docs/THIRD_PARTY_ATTRIBUTION.md`](docs/THIRD_PARTY_ATTRIBUTION.md)

## Troubleshooting

- **SQLite cannot open the database:** run from the repository root; the engine creates the configured parent directory.
- **Raw hash/count mismatch:** do not overwrite `data/raw/creditcard.csv`; verify the source is the pinned 284,807-row ULB file.
- **Immutable-copy mismatch:** review which source changed, then remove/regenerate local outputs only after confirming provenance.
- **Scorer schema error:** preserve exact field names and order; synthetic AML rows are intentionally not ML-eligible.
- **Artifact import error:** rerun preparation and training in the same Python 3.11 environment.

## Current Scope

This is a synthetic-data hackathon/research prototype, not a production AML, legal-reporting, or automated decision system. No real customer data should be used.
