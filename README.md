# Suspicious Activity Detection Platform

Query-aware, deterministic-first AML investigation prototype for a hackathon/research MVP.

Phase 0 establishes the API foundation and versioned contracts only. Data ingestion, detection tools, orchestration, risk logic, and the frontend are implemented in later phases described in [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md).

## Requirements

- Python 3.11
- Git
- Windows PowerShell, macOS, or Linux shell

The current workspace also contains a large ULB/Kaggle CSV and an imported third-party fraud repository. They are reference inputs and are not imported by the Phase 0 application.

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

## Project Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- [`docs/IMPLEMENTATION_ROADMAP.md`](docs/IMPLEMENTATION_ROADMAP.md)
- [`docs/CONTRACTS.md`](docs/CONTRACTS.md)
- [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md)
- [`docs/THIRD_PARTY_ATTRIBUTION.md`](docs/THIRD_PARTY_ATTRIBUTION.md)

## Current Scope

This is a synthetic-data hackathon prototype, not a production AML or legal reporting system. No real customer data should be used. The imported fraud repository has no supplied license and remains reference-only.
