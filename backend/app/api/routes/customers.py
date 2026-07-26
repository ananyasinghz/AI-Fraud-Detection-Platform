"""Customer entity lookup routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from backend.app.api.dependencies import SessionDep
from backend.app.core.errors import AppError
from backend.app.data.repositories import CustomerRepository, TransactionRepository
from backend.app.domain.api import (
    CustomerDetailResponse,
    CustomerListResponse,
    CustomerResponse,
    CustomerTransactionSummary,
)

# Demo catalog clock — matches frontend DEMO_AS_OF.
_DEMO_AS_OF = datetime(2026, 7, 25, tzinfo=UTC)

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


@router.get("/customers/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer(customer_id: str, session: SessionDep) -> CustomerDetailResponse:
    customer = CustomerRepository(session).get_by_id(customer_id)
    if customer is None:
        raise AppError(code="CUSTOMER_NOT_FOUND", message="customer not found", status_code=404)

    resolution = CustomerRepository(session).get_profile_as_of(customer_id, _DEMO_AS_OF)
    profile = resolution.profile
    txs = TransactionRepository(session).list_recent_for_customer(
        customer_id,
        as_of=_DEMO_AS_OF,
        limit=20,
    )
    return CustomerDetailResponse(
        customer_id=customer.customer_id,
        created_at=customer.created_at,
        status=customer.status,
        segment=profile.segment if profile is not None else None,
        residence_country=profile.residence_country if profile is not None else None,
        kyc_risk_rating=profile.kyc_risk_rating if profile is not None else None,
        recent_transactions=[
            CustomerTransactionSummary(
                transaction_id=tx.transaction_id,
                amount_minor=tx.amount_minor,
                currency=tx.currency,
                occurred_at=tx.occurred_at,
                transaction_type=tx.transaction_type,
            )
            for tx in txs
        ],
    )
