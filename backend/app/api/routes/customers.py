"""Customer entity lookup routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.app.api.dependencies import SessionDep
from backend.app.core.errors import AppError
from backend.app.data.repositories import CustomerRepository
from backend.app.domain.api import CustomerListResponse, CustomerResponse

router = APIRouter(tags=["customers"])


@router.get("/customers", response_model=CustomerListResponse)
async def list_customers(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> CustomerListResponse:
    rows, total = CustomerRepository(session).list_customers(limit=limit, offset=offset)
    return CustomerListResponse(
        items=[
            CustomerResponse(
                customer_id=row.customer_id,
                created_at=row.created_at,
                status=row.status,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


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
