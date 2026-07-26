"""Resolve ml_feature_ref values without importing backend.app.ml at module load."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

RAW_FEATURE_ORDER = (
    "Time",
    "V1",
    "V2",
    "V3",
    "V4",
    "V5",
    "V6",
    "V7",
    "V8",
    "V9",
    "V10",
    "V11",
    "V12",
    "V13",
    "V14",
    "V15",
    "V16",
    "V17",
    "V18",
    "V19",
    "V20",
    "V21",
    "V22",
    "V23",
    "V24",
    "V25",
    "V26",
    "V27",
    "V28",
    "Amount",
)


def resolve_fixture_path(feature_ref: str, *, workspace: Path | None = None) -> tuple[Path, int]:
    """Parse refs like ``fixture:creditcard_tiny.csv:0`` into path + 0-based data row."""
    if not feature_ref.startswith("fixture:"):
        raise ValueError("unsupported ml_feature_ref; expected fixture:<file>:<row>")
    parts = feature_ref.split(":")
    if len(parts) != 3:
        raise ValueError("ml_feature_ref must be fixture:<file>:<row>")
    _, filename, row_text = parts
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ValueError("fixture filename must be a bare file name")
    row = int(row_text)
    if row < 0:
        raise ValueError("fixture row must be non-negative")
    root = workspace or Path.cwd()
    path = root / "backend" / "tests" / "fixtures" / filename
    if not path.is_file():
        raise FileNotFoundError(f"fixture not found: {path}")
    return path, row


def load_ulb_features(feature_ref: str, *, workspace: Path | None = None) -> dict[str, float]:
    """Load ordered ULB features via the stdlib csv module."""
    path, row_index = resolve_fixture_path(feature_ref, workspace=workspace)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if row_index >= len(rows):
        raise IndexError(f"fixture row {row_index} out of range for {path.name}")
    source = rows[row_index]
    features: dict[str, float] = {}
    for name in RAW_FEATURE_ORDER:
        if name not in source:
            raise KeyError(f"fixture missing column {name}")
        features[name] = float(source[name])
    return features


def features_as_mapping(features: dict[str, float]) -> dict[str, Any]:
    """Return features in the exact scorer column order."""
    return {name: features[name] for name in RAW_FEATURE_ORDER}
