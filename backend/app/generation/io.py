"""Runtime-bundle persistence without access to evaluation manifests."""

import json
from pathlib import Path

from backend.app.generation.contracts import RuntimeBundle


def write_runtime_bundle(bundle: RuntimeBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_runtime_bundle(path: Path) -> RuntimeBundle:
    return RuntimeBundle.model_validate_json(path.read_text(encoding="utf-8"))
