"""FastAPI application factory."""

from fastapi import FastAPI

from backend.app.api.routes.health import router as health_router
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import register_exception_handlers
from backend.app.core.logging import configure_logging
from backend.app.core.request_id import RequestIdMiddleware


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
    application.add_middleware(RequestIdMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router, prefix=resolved.api_prefix)
    return application


app = create_app()
