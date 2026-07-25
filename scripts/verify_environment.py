"""Verify core imports without loading data, models, labels, or reference code."""

import json
import sys
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.main import app


def main() -> None:
    settings = get_settings()
    workspace = Path.cwd().resolve()
    forbidden_roots = (
        workspace / "dataset",
        workspace / "Fraud Detection",
        workspace / "Credit-Card-Fraud-Detection",
        settings.model_dir.resolve(),
        (settings.data_dir / "evaluation").resolve(),
    )
    loaded_paths = [
        Path(path).resolve()
        for module in sys.modules.values()
        if (path := str(getattr(module, "__file__", "") or ""))
    ]
    unexpectedly_loaded = [
        str(path)
        for path in loaded_paths
        if any(path.is_relative_to(root) for root in forbidden_roots)
    ]
    forbidden_modules = [
        name for name in sys.modules if name.startswith(("backend.app.ml", "backend.evaluation"))
    ]
    if unexpectedly_loaded or forbidden_modules:
        raise RuntimeError(f"forbidden runtime load(s): {unexpectedly_loaded + forbidden_modules}")
    print(
        json.dumps(
            {
                "app": app.title,
                "contract_version": settings.contract_version,
                "environment": settings.environment,
                "forbidden_imports_loaded": False,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
