"""Deterministic route → intent mapping until Phase 5 NLU lands."""

from __future__ import annotations

from backend.app.domain.enums import IntentType, RouteType

_ROUTE_INTENT: dict[RouteType, IntentType] = {
    RouteType.SIMPLE_LOOKUP: IntentType.SIMPLE_LOOKUP,
    RouteType.FEATURE_ONLY: IntentType.FEATURE_COMPARISON,
    RouteType.FULL_INVESTIGATION: IntentType.ENTITY_INVESTIGATION,
}


def intent_from_route(route: RouteType) -> IntentType:
    return _ROUTE_INTENT[route]
