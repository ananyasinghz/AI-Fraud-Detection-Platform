"""Service health endpoint."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import settings_from_request
from backend.app.core.config import Settings
from backend.app.domain.base import ContractModel

router = APIRouter(tags=["system"])


class HealthResponse(ContractModel):
    """Stable health-check response."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str
    contract_version: Literal["v1"]
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(settings_from_request)],
) -> HealthResponse:
    """Report process health without touching data or model dependencies."""
    return HealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        contract_version=settings.contract_version,
        timestamp=datetime.now(UTC),
    )
