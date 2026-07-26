"""FastAPI application factory."""

from fastapi import FastAPI

from backend.app.api.routes.alerts import router as alerts_router
from backend.app.api.routes.customers import router as customers_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.investigations import router as investigations_router
from backend.app.api.routes.query import router as query_router
from backend.app.api.routes.transactions import router as transactions_router
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.request_id import RequestIdMiddleware
from backend.app.data.database import engine_from_settings, session_factory
from backend.app.services.scoring import build_scorer_factory
from backend.app.tools.registry import TOOL_REGISTRY


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build an isolated app instance for runtime or tests."""
    resolved = settings or get_settings()
    configure_logging(resolved.log_level)

    application = FastAPI(
        title=resolved.app_name,
        version=resolved.app_version,
        debug=resolved.debug,
    )
    application.state.settings = resolved
    application.state.engine = engine_from_settings(resolved)
    application.state.session_factory = session_factory(application.state.engine)
    application.state.tool_registry = TOOL_REGISTRY
    application.state.scorer_factory = build_scorer_factory(resolved)
    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)

    prefix = resolved.api_prefix
    application.include_router(health_router, prefix=prefix)
    application.include_router(query_router, prefix=prefix)
    application.include_router(investigations_router, prefix=prefix)
    application.include_router(customers_router, prefix=prefix)
    application.include_router(transactions_router, prefix=prefix)
    application.include_router(alerts_router, prefix=prefix)
    return application


app = create_app()
