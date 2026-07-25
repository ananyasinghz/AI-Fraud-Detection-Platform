"""Idempotent persistence of label-free runtime scenario bundles."""

from datetime import UTC

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.data.models import (
    Account,
    Counterparty,
    Customer,
    CustomerProfile,
    DatasetRun,
    Device,
    Transaction,
)
from backend.app.data.repositories import CustomerRepository
from backend.app.domain.base import ContractModel
from backend.app.generation.contracts import RuntimeBundle


class SeedResult(ContractModel):
    run_id: str
    created: bool
    fingerprint: str
    counts: dict[str, int] = Field(default_factory=dict)


def bundle_counts(bundle: RuntimeBundle) -> dict[str, int]:
    return {
        "customers": len(bundle.customers),
        "customer_profiles": len(bundle.profiles),
        "accounts": len(bundle.accounts),
        "counterparties": len(bundle.counterparties),
        "devices": len(bundle.devices),
        "transactions": len(bundle.transactions),
    }


def seed_runtime_bundle(
    session: Session,
    bundle: RuntimeBundle,
    *,
    alembic_revision: str = "0001",
) -> SeedResult:
    """Insert a generated run once, rejecting run-ID/fingerprint drift."""
    existing = session.get(DatasetRun, bundle.run_id)
    counts = bundle_counts(bundle)
    if existing is not None:
        if existing.source_fingerprint != bundle.fingerprint:
            raise ValueError(f"run {bundle.run_id} already exists with a different fingerprint")
        actual_transactions = session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.seed_run_id == bundle.run_id)
        )
        if actual_transactions != counts["transactions"]:
            raise ValueError(f"run {bundle.run_id} is partially seeded")
        return SeedResult(
            run_id=bundle.run_id,
            created=False,
            fingerprint=bundle.fingerprint,
            counts=counts,
        )

    session.add(
        DatasetRun(
            run_id=bundle.run_id,
            run_kind="aml_seed",
            generator_version=bundle.generator_version,
            alembic_revision=alembic_revision,
            random_seed=bundle.seed,
            split_name=bundle.split,
            source_fingerprint=bundle.fingerprint,
            record_counts=counts,
            created_at=bundle.generated_at.astimezone(UTC),
        )
    )
    for customer_record in bundle.customers:
        session.add(
            Customer(
                customer_id=customer_record.customer_id,
                created_at=customer_record.created_at,
                status=customer_record.status,
            )
        )
    session.flush()

    profile_repository = CustomerRepository(session)
    for profile_record in sorted(
        bundle.profiles,
        key=lambda item: (item.customer_id, item.profile_effective_from),
    ):
        profile_repository.add_profile(
            CustomerProfile(
                customer_id=profile_record.customer_id,
                segment=profile_record.segment,
                residence_country=profile_record.residence_country,
                occupation_or_industry=profile_record.occupation_or_industry,
                declared_annual_income_minor=profile_record.declared_annual_income_minor,
                declared_revenue_band=profile_record.declared_revenue_band,
                income_currency=profile_record.income_currency,
                expected_monthly_volume_min_minor=(
                    profile_record.expected_monthly_volume_min_minor
                ),
                expected_monthly_volume_max_minor=(
                    profile_record.expected_monthly_volume_max_minor
                ),
                volume_currency=profile_record.volume_currency,
                kyc_risk_rating=profile_record.kyc_risk_rating,
                pep_flag=profile_record.pep_flag,
                profile_effective_from=profile_record.profile_effective_from,
                profile_effective_to=profile_record.profile_effective_to,
                profile_source=profile_record.profile_source,
            )
        )
        session.flush()

    for account_record in bundle.accounts:
        session.add(
            Account(
                account_id=account_record.account_id,
                customer_id=account_record.customer_id,
                account_type=account_record.account_type,
                currency=account_record.currency,
                country=account_record.country,
                opened_at=account_record.opened_at,
                status=account_record.status,
            )
        )
    for counterparty_record in bundle.counterparties:
        session.add(
            Counterparty(
                counterparty_id=counterparty_record.counterparty_id,
                display_name=counterparty_record.display_name,
                country=counterparty_record.country,
                kind=counterparty_record.kind,
            )
        )
    for device_record in bundle.devices:
        session.add(
            Device(
                device_id=device_record.device_id,
                device_type=device_record.device_type,
                first_seen_at=device_record.first_seen_at,
                last_seen_at=device_record.last_seen_at,
            )
        )
    session.flush()

    for transaction_record in bundle.transactions:
        session.add(
            Transaction(
                transaction_id=transaction_record.transaction_id,
                account_id=transaction_record.account_id,
                customer_id=transaction_record.customer_id,
                occurred_at=transaction_record.occurred_at,
                posted_at=transaction_record.posted_at,
                amount_minor=transaction_record.amount_minor,
                currency=transaction_record.currency,
                direction=transaction_record.direction,
                transaction_type=transaction_record.transaction_type,
                channel=transaction_record.channel,
                country=transaction_record.country,
                counterparty_id=transaction_record.counterparty_id,
                counterparty_account_id=transaction_record.counterparty_account_id,
                device_id=transaction_record.device_id,
                ml_eligible=transaction_record.ml_eligible,
                ml_feature_ref=transaction_record.ml_feature_ref,
                data_source=transaction_record.data_source,
                seed_run_id=bundle.run_id,
            )
        )
    session.flush()
    return SeedResult(
        run_id=bundle.run_id,
        created=True,
        fingerprint=bundle.fingerprint,
        counts=counts,
    )
