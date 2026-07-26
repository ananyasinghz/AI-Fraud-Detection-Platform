"""Transaction entity lookup and scoring routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from backend.app.api.dependencies import SessionDep, get_scorer_factory
from backend.app.core.errors import AppError
from backend.app.data.repositories import TransactionRepository
from backend.app.domain.api import ScoreResponse, TransactionResponse
from backend.app.services.scoring import score_transaction

router = APIRouter(tags=["transactions"])


@router.get("/transactions/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(transaction_id: str, session: SessionDep) -> TransactionResponse:
    transaction = TransactionRepository(session).get_by_id(transaction_id)
    if transaction is None:
        raise AppError(
            code="TRANSACTION_NOT_FOUND",
            message="transaction not found",
            status_code=404,
        )
    return TransactionResponse(
        transaction_id=transaction.transaction_id,
        customer_id=transaction.customer_id,
        account_id=transaction.account_id,
        occurred_at=transaction.occurred_at,
        amount_minor=transaction.amount_minor,
        currency=transaction.currency,
        direction=transaction.direction,
        transaction_type=transaction.transaction_type,
        channel=transaction.channel,
        country=transaction.country,
        ml_eligible=transaction.ml_eligible,
        ml_feature_ref=transaction.ml_feature_ref,
        data_source=transaction.data_source,
    )


@router.post("/transactions/{transaction_id}/score", response_model=ScoreResponse)
async def score_one_transaction(
    transaction_id: str,
    request: Request,
    session: SessionDep,
) -> ScoreResponse:
    return score_transaction(
        session,
        transaction_id,
        scorer_factory=get_scorer_factory(request),
    )
