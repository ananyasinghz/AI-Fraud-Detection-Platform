"""Customer entity lookup routes."""

from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.dependencies import SessionDep
from backend.app.core.errors import AppError
from backend.app.data.repositories import CustomerRepository
from backend.app.domain.api import CustomerResponse

router = APIRouter(tags=["customers"])


@router.get("/customers/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: str, session: SessionDep) -> CustomerResponse:
    customer = CustomerRepository(session).get_by_id(customer_id)
    if customer is None:
        raise AppError(code="CUSTOMER_NOT_FOUND", message="customer not found", status_code=404)
    return CustomerResponse(
        customer_id=customer.customer_id,
        created_at=customer.created_at,
        status=customer.status,
    )
