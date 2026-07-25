"""FastAPI dependencies."""

from fastapi import Request

from backend.app.core.config import Settings


def settings_from_request(request: Request) -> Settings:
    """Return the settings instance used to create this app."""
    settings: Settings = request.app.state.settings
    return settings
