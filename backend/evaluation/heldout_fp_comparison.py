"""Held-out false-positive comparison: naive baseline vs contextual detector.

Evaluation-only. Uses seed 99 / held_out only. Never reads labels while applying
thresholds or rules; labels are joined after scoring for metrics.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import EntityType, IntentType, RiskLevel, RouteType, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.generation.io import write_runtime_bundle
from backend.app.generation.orchestrator import generate_scenarios
from backend.app.generation.seeder import seed_runtime_bundle
from backend.app.nlu.templates import _phase8_suspicious_chain
from backend.app.policy.config import load_policy_config
from backend.app.risk.escalation import recommend_escalation
from backend.app.risk.policy import load_risk_policy
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY
from backend.app.workflow.graph import GraphExecutor
from backend.app.workflow.state import InvestigationState
from backend.evaluation.naive_baseline import apply_naive_baseline, load_naive_baseline_config
from backend.evaluation.scenario_manifest import build_manifest, write_manifest

AS_OF = datetime(2026, 7, 25, tzinfo=UTC)
DEFAULT_BASELINE = Path("config/evaluation/naive_baseline.v1.yaml")


@dataclass(frozen=True)
class Confusion:
    alerts: int
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def fpr(self) -> float:
        denom = self.fp + self.tn
        return (self.fp / denom) if denom else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return (self.tp / denom) if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return (self.tp / denom) if denom else 0.0

    def alerts_per_1000(self, population: int) -> float:
        return (self.alerts / population * 1000.0) if population else 0.0

    def as_dict(self, population: int) -> dict[str, float | int]:
        return {
            "alerts_raised": self.alerts,
            "true_positives": self.tp,
            "false_positives": self.fp,
            "true_negatives": self.tn,
            "false_negatives": self.fn,
            "false_positive_rate": round(self.fpr, 6),
            "alerts_per_1000": round(self.alerts_per_1000(population), 4),
            "precision": round(self.precision, 6),
            "recall": round(self.recall, 6),
        }


def _confusion(alerted: set[str], positives: set[str], population: set[str]) -> Confusion:
    tp = len(alerted & positives)
    fp = len(alerted - positives)
    tn = len((population - positives) - alerted)
    fn = len(positives - alerted)
    return Confusion(alerts=len(alerted), tp=tp, fp=fp, tn=tn, fn=fn)


def _positive_customers(annotations: Iterable[Any]) -> set[str]:
    positives: set[str] = set()
    for item in annotations:
        if item.pattern_type == "clean_control":
            continue
        if item.entity_type == "customer":
            positives.add(item.entity_id)
    return positives


def _naive_alerted_customers(runtime: Any, config_path: Path) -> set[str]:
    config = load_naive_baseline_config(config_path)
    result = apply_naive_baseline(runtime, config)
    txn_to_customer = {txn.transaction_id: txn.customer_id for txn in runtime.transactions}
    alerted: set[str] = set()
    for amount_flag in result.amount_flags:
        customer_id = txn_to_customer.get(amount_flag.transaction_id)
        if customer_id:
            alerted.add(customer_id)
    for daily_flag in result.daily_count_flags:
        alerted.add(daily_flag.customer_id)
    return alerted


def _entity_plan(customer_id: str, *, include_profile_context: bool) -> ValidatedPlan:
    del include_profile_context  # profile/context enter via risk params when present in prior tools
    return ValidatedPlan(
        strategy="heldout_contextual",
        planner_version="evaluation_v1",
        steps=[
            PlanStep(
                step_id="feat1",
                tool=ToolName.FEATURE_ENGINEERING,
                operation="compute_feature",
                parameters={
                    "feature_operation": "subthreshold_count",
                    "entity_ids": [customer_id],
                    "window_days": 30,
                    "currency": "USD",
                },
                reason="contextual structuring feature",
            ),
            PlanStep(
                step_id="anom1",
                tool=ToolName.ANOMALY_DETECTION,
                operation="detect",
                parameters={"mode": "rules_only", "entity_id": customer_id},
                reason="contextual rules signal",
                depends_on=["feat1"],
            ),
            *_phase8_suspicious_chain(
                depends_on=["anom1"],
                entity_id=customer_id,
                classify_op="classify_customer",
                required=False,
            ),
        ],
    )


def _contextual_alerted(
    *,
    database_url: str,
    customer_ids: list[str],
    settings: Settings,
    rules_profile_only: bool,
) -> set[str]:
    """Run rules → Phase 8 risk/escalation per customer; alert if review/report."""
    del rules_profile_only  # current anomaly facade is rules-only; documented as ablation N/A
    engine = create_database_engine(database_url)
    alerted: set[str] = set()
    policy = load_policy_config(settings.policy_config_path)
    risk_policy = load_risk_policy(settings.risk_policy_path)
    with session_scope(session_factory(engine)) as session:
        for customer_id in customer_ids:
            plan = _entity_plan(customer_id, include_profile_context=True)
            state = InvestigationState(
                request_id=f"eval-{customer_id}",
                query=f"evaluate {customer_id}",
                route=RouteType.FULL_INVESTIGATION,
                detected_intent=IntentType.ENTITY_INVESTIGATION,
                filters=NormalizedFilters(customer_ids=[customer_id]),
                plan=plan,
                as_of=AS_OF,
                investigation_id=None,
            )
            context = ToolContext(
                session=session,
                policy=policy,
                settings=settings,
                filters=state.filters,
                as_of=AS_OF,
                request_id=state.request_id,
                investigation_id=None,
            )
            outcome = GraphExecutor(registry=TOOL_REGISTRY, settings=settings).execute(
                state,
                context=context,
            )
            esc = next(
                (
                    item
                    for item in reversed(outcome.state.tool_results)
                    if item.tool == ToolName.ESCALATION and item.data
                ),
                None,
            )
            if esc and (
                esc.data.get("alert_created")
                or str(esc.data.get("escalation_action") or "").lower() in {"review", "report"}
            ):
                alerted.add(customer_id)
                continue
            # Fallback: derive from risk level if escalation skipped.
            risk = next(
                (
                    item
                    for item in reversed(outcome.state.tool_results)
                    if item.tool == ToolName.RISK_CLASSIFICATION and item.data
                ),
                None,
            )
            if risk and risk.data.get("risk_level") in {
                RiskLevel.MEDIUM.value,
                RiskLevel.HIGH.value,
            }:
                raw_score = risk.data.get("risk_score")
                raw_confidence = risk.data.get("confidence")
                raw_reasons = risk.data.get("reasons")
                raw_evidence = risk.data.get("evidence_ids")
                rec = recommend_escalation(
                    entity_type=EntityType.CUSTOMER.value,
                    entity_id=customer_id,
                    risk_score=float(raw_score) if isinstance(raw_score, (int, float)) else 0.0,
                    risk_level=RiskLevel(str(risk.data["risk_level"])),
                    confidence=(
                        float(raw_confidence) if isinstance(raw_confidence, (int, float)) else 0.0
                    ),
                    reasons=(
                        [str(item) for item in raw_reasons] if isinstance(raw_reasons, list) else []
                    ),
                    evidence_ids=(
                        [str(item) for item in raw_evidence]
                        if isinstance(raw_evidence, list)
                        else []
                    ),
                    policy=risk_policy,
                    window_start=AS_OF - timedelta(days=30),
                    window_end=AS_OF,
                )
                if rec.should_create_alert:
                    alerted.add(customer_id)
    engine.dispose()
    return alerted


def ensure_heldout(seed: int, data_dir: Path) -> tuple[Any, Any]:
    result = generate_scenarios(
        seed=seed,
        split="held_out",
        generation_config_path=Path("config/generation/scenario_catalog.v1.yaml"),
        policy_config_path=Path("config/policy/reporting_thresholds.v1.yaml"),
    )
    bundle_dir = data_dir / "generated" / "held_out" / f"seed-{seed}"
    write_runtime_bundle(result.runtime, bundle_dir / "runtime_bundle.json")
    manifest = build_manifest(result)
    write_manifest(manifest, data_dir / "evaluation" / "held_out" / f"seed-{seed}.json")
    return result.runtime, result.annotations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=99)
    parser.add_argument("--baseline-config", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument(
        "--output", type=Path, default=Path("data/evaluation/held_out/fp_baseline_seed-99.json")
    )
    parser.add_argument("--workdir", type=Path, default=Path("data/evaluation/held_out/_workdir"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.seed != 99:
        raise SystemExit("Phase 9 FP comparison must use held-out seed 99")
    settings = Settings.model_validate(
        {
            "environment": "test",
            "database_url": f"sqlite:///{(args.workdir / 'heldout.db').as_posix()}",
            "data_dir": args.workdir / "data",
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "risk_enabled": True,
            "explanation_enabled": True,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
            "risk_policy_path": Path("config/policy/risk_scoring.v1.yaml"),
        }
    )
    args.workdir.mkdir(parents=True, exist_ok=True)
    runtime, annotations = ensure_heldout(args.seed, Path("data"))

    positives = _positive_customers(annotations)
    population = {customer.customer_id for customer in runtime.customers}
    naive_alerted = _naive_alerted_customers(runtime, args.baseline_config)

    engine = create_database_engine(settings.database_url)
    Base.metadata.create_all(engine)
    with session_scope(session_factory(engine)) as session:
        seed_runtime_bundle(session, runtime, alembic_revision="head")
    engine.dispose()

    started = time.perf_counter()
    contextual_alerted = _contextual_alerted(
        database_url=settings.database_url,
        customer_ids=sorted(population),
        settings=settings,
        rules_profile_only=False,
    )
    elapsed_s = time.perf_counter() - started

    naive = _confusion(naive_alerted, positives, population)
    contextual = _confusion(contextual_alerted, positives, population)
    n = len(population)
    payload = {
        "benchmark_version": "heldout_fp_comparison.v1",
        "seed": args.seed,
        "split": "held_out",
        "as_of": AS_OF.isoformat(),
        "population_customers": n,
        "positive_customers": len(positives),
        "prevalence": round(len(positives) / n, 6) if n else 0.0,
        "naive_fixed_threshold_baseline": naive.as_dict(n),
        "contextual_detector": contextual.as_dict(n),
        "ablations": {
            "rules_profile_only": (
                "Current anomaly facade evaluates structuring.v1 rules only; "
                "profile/context enter customer rollup at ≤5% weight when supplied. "
                "No separate ablation numbers beyond the contextual row above."
            ),
            "ml_incremental": (
                "Synthetic held-out AML rows are ml_eligible=false; ML incremental "
                "effect is not measurable on this population."
            ),
        },
        "limitations": [
            "Synthetic scenario prevalence is injected and does not mirror real AML base rates.",
            "Ground truth is scenario annotations (pattern_type != clean_control), "
            "not SAR outcomes.",
            "Contextual path uses entity-scoped features + structuring rules + "
            "Phase 8 risk/escalation.",
            "Naive baseline flags amount/daily-count thresholds without profile "
            "or rolling context.",
        ],
        "timing": {
            "contextual_scan_seconds": round(elapsed_s, 3),
            "machine_note": "Local developer machine; not a controlled latency bench.",
        },
        "runtime_fingerprint": runtime.fingerprint,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
