"""Offline storage for hidden synthetic scenario ground truth."""

import json
from pathlib import Path

from pydantic import Field

from backend.app.domain.base import ContractModel
from backend.app.generation.contracts import GenerationResult, ScenarioAnnotation


class EvaluationManifest(ContractModel):
    manifest_version: str = "scenario_manifest.v1"
    runtime_fingerprint: str
    seed: int = Field(ge=0)
    split: str
    scenarios: list[ScenarioAnnotation]


def build_manifest(result: GenerationResult) -> EvaluationManifest:
    return EvaluationManifest(
        runtime_fingerprint=result.runtime.fingerprint,
        seed=result.runtime.seed,
        split=result.runtime.split,
        scenarios=result.annotations,
    )


def write_manifest(manifest: EvaluationManifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_manifest(path: Path) -> EvaluationManifest:
    return EvaluationManifest.model_validate_json(path.read_text(encoding="utf-8"))
