"""Integration: Phase 8 suspicious chain vs SQL-only omission."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.data.database import create_database_engine, session_factory, session_scope
from backend.app.data.models import Base
from backend.app.domain.enums import IntentType, RouteType, ToolName
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.plan import PlanStep, ValidatedPlan
from backend.app.generation.orchestrator import generate_scenarios
from backend.app.generation.seeder import seed_runtime_bundle
from backend.app.main import create_app
from backend.app.policy.config import load_policy_config
from backend.app.tools.context import ToolContext
from backend.app.tools.registry import TOOL_REGISTRY
from backend.app.workflow.graph import GraphExecutor
from backend.app.workflow.state import InvestigationState

AS_OF = datetime(2026, 2, 15, tzinfo=UTC)
POLICY = load_policy_config(Path("config/policy/reporting_thresholds.v1.yaml"))


def _client(tmp_path: Path) -> TestClient:
    db = tmp_path / "p8.db"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_database_engine(url)
    Base.metadata.create_all(engine)
    result = generate_scenarios(
        seed=42,
        split="dev",
        generation_config_path=Path("config/generation/scenario_catalog.v1.yaml"),
        policy_config_path=Path("config/policy/reporting_thresholds.v1.yaml"),
    )
    with session_scope(session_factory(engine)) as session:
        seed_runtime_bundle(session, result.runtime, alembic_revision="head")
    settings = Settings.model_validate(
        {
            "environment": "test",
            "app_name": "Phase8",
            "database_url": url,
            "data_dir": tmp_path / "data",
            "chroma_persist_dir": tmp_path / "chroma",
            "policy_corpus_path": Path("config/policy/corpus/policy_excerpts.v1.json"),
            "ollama_enabled": False,
            "planner_enabled": False,
            "ml_enabled": False,
            "risk_enabled": True,
            "explanation_enabled": True,
            "policy_config_path": Path("config/policy/reporting_thresholds.v1.yaml"),
            "risk_policy_path": Path("config/policy/risk_scoring.v1.yaml"),
        }
    )
    return TestClient(create_app(settings))


def test_sql_only_query_omits_phase8_tools(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/api/v1/query",
        json={"query": "Show me transactions over $10,000.", "as_of": AS_OF.isoformat()},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    invoked = set(body["execution_summary"]["tools_invoked"])
    assert ToolName.SQL_LOOKUP.value in invoked
    assert ToolName.VERIFICATION.value not in invoked
    assert ToolName.RISK_CLASSIFICATION.value not in invoked
    assert ToolName.ESCALATION.value not in invoked
    assert ToolName.EXPLANATION.value not in invoked


def test_suspicious_plan_invokes_phase8_chain(tmp_path: Path) -> None:
    db = tmp_path / "chain.db"
    url = f"sqlite:///{db.as_posix()}"
    engine = create_database_engine(url)
    Base.metadata.create_all(engine)
    result = generate_scenarios(
        seed=42,
        split="dev",
        generation_config_path=Path("config/generation/scenario_catalog.v1.yaml"),
        policy_config_path=Path("config/policy/reporting_thresholds.v1.yaml"),
    )
    customer_id = result.runtime.customers[0].customer_id
    with session_scope(session_factory(engine)) as session:
        seed_runtime_bundle(session, result.runtime, alembic_revision="head")
        plan = ValidatedPlan(
            strategy="phase8_chain",
            planner_version="test.v1",
            steps=[
                PlanStep(
                    step_id="sql1",
                    tool=ToolName.SQL_LOOKUP,
                    operation="get_customer",
                    parameters={"customer_id": customer_id},
                    reason="load",
                ),
                PlanStep(
                    step_id="anom1",
                    tool=ToolName.ANOMALY_DETECTION,
                    operation="detect",
                    parameters={"mode": "rules_only", "entity_id": customer_id},
                    reason="signals",
                    depends_on=["sql1"],
                    required=False,
                ),
                PlanStep(
                    step_id="verify1",
                    tool=ToolName.VERIFICATION,
                    operation="verify_evidence",
                    parameters={},
                    reason="stage1",
                    depends_on=["anom1"],
                    required=False,
                ),
                PlanStep(
                    step_id="risk1",
                    tool=ToolName.RISK_CLASSIFICATION,
                    operation="classify_customer",
                    parameters={"entity_id": customer_id},
                    reason="risk",
                    depends_on=["verify1"],
                    required=False,
                ),
                PlanStep(
                    step_id="consist1",
                    tool=ToolName.VERIFICATION,
                    operation="verify_risk_consistency",
                    parameters={},
                    reason="stage2",
                    depends_on=["risk1"],
                    required=False,
                ),
                PlanStep(
                    step_id="esc1",
                    tool=ToolName.ESCALATION,
                    operation="recommend",
                    parameters={},
                    reason="escalate",
                    depends_on=["consist1"],
                    required=False,
                ),
                PlanStep(
                    step_id="expl1",
                    tool=ToolName.EXPLANATION,
                    operation="explain",
                    parameters={},
                    reason="explain",
                    depends_on=["esc1"],
                    required=False,
                ),
            ],
        )
        state = InvestigationState(
            request_id="req-p8-int",
            query="investigate",
            route=RouteType.FULL_INVESTIGATION,
            detected_intent=IntentType.ENTITY_INVESTIGATION,
            filters=NormalizedFilters(customer_ids=[customer_id]),
            plan=plan,
            as_of=AS_OF,
            investigation_id="inv-p8-int",
        )
        context = ToolContext(
            session=session,
            policy=POLICY,
            settings=Settings(
                environment="test",
                ollama_enabled=False,
                risk_enabled=True,
                explanation_enabled=True,
                risk_policy_path=Path("config/policy/risk_scoring.v1.yaml"),
            ),
            filters=NormalizedFilters(customer_ids=[customer_id]),
            as_of=AS_OF,
            request_id="req-p8-int",
            investigation_id="inv-p8-int",
        )
        outcome = GraphExecutor(
            registry=TOOL_REGISTRY,
            settings=context.settings,
        ).execute(state, context=context)

    invoked = {tool.value for tool in outcome.state.tools_invoked}
    assert ToolName.VERIFICATION.value in invoked
    assert ToolName.RISK_CLASSIFICATION.value in invoked
    assert ToolName.ESCALATION.value in invoked
    assert ToolName.EXPLANATION.value in invoked
    summary_tools = set(outcome.final_response.execution_summary.tools_invoked)
    assert ToolName.VERIFICATION in summary_tools or ToolName.RISK_CLASSIFICATION in summary_tools
