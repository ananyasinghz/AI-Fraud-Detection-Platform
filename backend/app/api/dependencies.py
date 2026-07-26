"""FastAPI dependencies for settings, sessions, policy, tools, and scorers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.domain.filters import NormalizedFilters
from backend.app.policy.config import PolicyConfig, load_policy_config
from backend.app.rules import RULE_ENGINE
from backend.app.services.scoring import build_scorer_factory
from backend.app.tools.context import FraudScorerProtocol, ToolContext
from backend.app.tools.features.registry import FEATURE_REGISTRY
from backend.app.tools.registry import TOOL_REGISTRY, ToolRegistry


def settings_from_request(request: Request) -> Settings:
    """Return the settings instance used to create this app."""
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """Yield a request-scoped DB session that commits on success."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@lru_cache(maxsize=8)
def _cached_policy(path: str) -> PolicyConfig:
    return load_policy_config(Path(path))


def get_policy(settings: Annotated[Settings, Depends(settings_from_request)]) -> PolicyConfig:
    return _cached_policy(str(settings.policy_config_path.resolve()))


def get_tool_registry(request: Request) -> ToolRegistry:
    registry: ToolRegistry = getattr(request.app.state, "tool_registry", TOOL_REGISTRY)
    return registry


def get_feature_registry() -> object:
    return FEATURE_REGISTRY


def get_rule_engine() -> object:
    return RULE_ENGINE


def get_scorer_factory(
    request: Request,
) -> Callable[[], FraudScorerProtocol | None]:
    factory = getattr(request.app.state, "scorer_factory", None)
    if factory is None:
        factory = build_scorer_factory(request.app.state.settings)
        request.app.state.scorer_factory = factory
    return factory


def build_tool_context(
    *,
    session: Session,
    settings: Settings,
    policy: PolicyConfig,
    filters: NormalizedFilters,
    as_of: datetime,
    request: Request,
) -> ToolContext:
    return ToolContext(
        session=session,
        policy=policy,
        settings=settings,
        filters=filters,
        as_of=as_of,
        scorer_factory=get_scorer_factory(request),
    )


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(settings_from_request)]
PolicyDep = Annotated[PolicyConfig, Depends(get_policy)]
RegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
