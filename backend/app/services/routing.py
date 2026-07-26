"""Parse free-text queries into routed template plans for execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.app.core.config import Settings
from backend.app.core.errors import AppError
from backend.app.domain.enums import IntentType, RouteType
from backend.app.domain.filters import NormalizedFilters
from backend.app.domain.intent import AnalysisRequest, ParsedIntent
from backend.app.domain.plan import ValidatedPlan
from backend.app.nlu.intent_parser import parse_intent
from backend.app.nlu.router import RoutingDecision, route_parsed_intent


@dataclass(frozen=True)
class ResolvedRequest:
    """Manual plan or NL-routed plan ready for the graph executor."""

    query: str
    as_of: datetime
    filters: NormalizedFilters
    plan: ValidatedPlan
    route: RouteType
    detected_intent: IntentType
    parsed_intent: ParsedIntent | None
    clarification: str | None = None
    needs_planner: bool = False


def resolve_for_execution(
    *,
    query: str,
    as_of: datetime,
    filters: NormalizedFilters,
    plan: ValidatedPlan | None,
    route: RouteType,
    detected_intent: IntentType | None,
    settings: Settings,
) -> ResolvedRequest:
    """If plan is supplied, use Phase 4 path; otherwise parse and route NL."""
    if plan is not None:
        intent = detected_intent
        if intent is None:
            from backend.app.workflow.intent import intent_from_route

            intent = intent_from_route(route)
        return ResolvedRequest(
            query=query,
            as_of=as_of,
            filters=filters,
            plan=plan,
            route=route,
            detected_intent=intent,
            parsed_intent=None,
        )

    analysis = AnalysisRequest(query=query, as_of=as_of, filters=filters)
    parsed = parse_intent(analysis, settings=settings)
    if detected_intent is not None:
        parsed = parsed.model_copy(update={"intent": detected_intent})
    decision: RoutingDecision = route_parsed_intent(
        parsed,
        confidence_floor=settings.intent_confidence_floor,
    )
    if decision.plan is None:
        raise AppError(
            code="CLARIFICATION_REQUIRED",
            message=decision.clarification or "Unable to route query without clarification",
            status_code=422,
            details={
                "needs_planner": decision.needs_planner,
                "parsed_intent": parsed.model_dump(mode="json"),
                "route": decision.route.value,
            },
        )
    return ResolvedRequest(
        query=query,
        as_of=as_of,
        filters=decision.filters,
        plan=decision.plan,
        route=decision.route,
        detected_intent=parsed.intent,
        parsed_intent=parsed,
        clarification=decision.clarification,
        needs_planner=decision.needs_planner,
    )
