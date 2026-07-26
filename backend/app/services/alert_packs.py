"""Filesystem sidecars for reviewer alert case packs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def alert_packs_dir(data_dir: Path) -> Path:
    path = data_dir / "runtime" / "alert_packs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pack_path(data_dir: Path, alert_id: str) -> Path:
    safe = "".join(ch for ch in alert_id if ch.isalnum() or ch in {"-", "_"})
    return alert_packs_dir(data_dir) / f"{safe}.json"


def write_alert_pack(data_dir: Path, alert_id: str, payload: dict[str, Any]) -> str:
    """Persist pack and return evidence_snapshot_ref."""
    path = pack_path(data_dir, alert_id)
    body = {**payload, "alert_id": alert_id}
    serialized = json.dumps(body, indent=2, sort_keys=True, default=str) + "\n"
    path.write_text(serialized, encoding="utf-8")
    return f"pack:{alert_id}"


def read_alert_pack(data_dir: Path, alert_id: str) -> dict[str, Any] | None:
    path = pack_path(data_dir, alert_id)
    if not path.is_file():
        # Also try resolving from evidence_snapshot_ref style pack:id
        if alert_id.startswith("pack:"):
            return read_alert_pack(data_dir, alert_id.removeprefix("pack:"))
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def read_alert_pack_from_ref(data_dir: Path, evidence_snapshot_ref: str) -> dict[str, Any] | None:
    if evidence_snapshot_ref.startswith("pack:"):
        return read_alert_pack(data_dir, evidence_snapshot_ref.removeprefix("pack:"))
    # Fallback: treat ref as alert id if a pack file exists
    return read_alert_pack(data_dir, evidence_snapshot_ref)
