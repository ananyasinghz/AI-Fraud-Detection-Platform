"""Application error types and FastAPI handlers."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """A safe, expected application error."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable error envelope without leaking internals."""
    if not isinstance(exc, AppError):
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": getattr(request.state, "request_id", None),
            }
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register handlers for expected application errors."""
    app.add_exception_handler(AppError, app_error_handler)
