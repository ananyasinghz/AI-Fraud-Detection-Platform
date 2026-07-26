"""Phase 1 relational schema."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.app.data.types import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class DatasetRun(Base):
    __tablename__ = "dataset_runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    generator_version: Mapped[str | None] = mapped_column(String(64))
    alembic_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    random_seed: Mapped[int | None] = mapped_column(Integer)
    split_name: Mapped[str | None] = mapped_column(String(32))
    source_fingerprint: Mapped[str | None] = mapped_column(String(128))
    record_counts: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "run_kind IN ('aml_seed', 'ml_prepare')",
            name="valid_run_kind",
        ),
    )


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'closed')",
            name="valid_customer_status",
        ),
    )


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"

    profile_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
    )
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    residence_country: Mapped[str] = mapped_column(String(2), nullable=False)
    occupation_or_industry: Mapped[str | None] = mapped_column(String(128))
    declared_annual_income_minor: Mapped[int | None] = mapped_column(Integer)
    declared_revenue_band: Mapped[str | None] = mapped_column(String(64))
    income_currency: Mapped[str | None] = mapped_column(String(3))
    expected_monthly_volume_min_minor: Mapped[int | None] = mapped_column(Integer)
    expected_monthly_volume_max_minor: Mapped[int | None] = mapped_column(Integer)
    volume_currency: Mapped[str | None] = mapped_column(String(3))
    kyc_risk_rating: Mapped[str | None] = mapped_column(String(16))
    pep_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    profile_effective_from: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    profile_effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime())
    profile_source: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "segment IN ('retail', 'sme', 'corporate')",
            name="valid_segment",
        ),
        CheckConstraint(
            "kyc_risk_rating IS NULL OR kyc_risk_rating IN ('low', 'medium', 'high')",
            name="valid_kyc_rating",
        ),
        CheckConstraint(
            "profile_effective_to IS NULL OR profile_effective_to > profile_effective_from",
            name="valid_profile_interval",
        ),
        CheckConstraint(
            "expected_monthly_volume_min_minor IS NULL OR expected_monthly_volume_min_minor >= 0",
            name="nonnegative_expected_min",
        ),
        CheckConstraint(
            "expected_monthly_volume_max_minor IS NULL "
            "OR expected_monthly_volume_max_minor >= expected_monthly_volume_min_minor",
            name="ordered_expected_volume",
        ),
        Index(
            "ix_profile_customer_effective",
            "customer_id",
            "profile_effective_from",
        ),
    )


class Account(Base):
    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
    )
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'closed')",
            name="valid_account_status",
        ),
        Index("ix_accounts_customer", "customer_id"),
    )


class Counterparty(Base):
    __tablename__ = "counterparties"

    counterparty_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    kind: Mapped[str | None] = mapped_column(String(64))


class Device(Base):
    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="valid_device_interval",
        ),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.customer_id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    country: Mapped[str | None] = mapped_column(String(2))
    counterparty_id: Mapped[str | None] = mapped_column(
        ForeignKey("counterparties.counterparty_id", ondelete="SET NULL"),
    )
    counterparty_account_id: Mapped[str | None] = mapped_column(String(128))
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.device_id", ondelete="SET NULL"),
    )
    ml_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ml_feature_ref: Mapped[str | None] = mapped_column(String(128))
    data_source: Mapped[str] = mapped_column(String(32), nullable=False)
    seed_run_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_runs.run_id", ondelete="RESTRICT"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("amount_minor >= 0", name="nonnegative_amount"),
        CheckConstraint(
            "direction IN ('credit', 'debit')",
            name="valid_direction",
        ),
        CheckConstraint(
            "data_source IN ('synthetic', 'ulb_attached')",
            name="valid_data_source",
        ),
        CheckConstraint(
            "(ml_eligible = 0 AND ml_feature_ref IS NULL) "
            "OR (ml_eligible = 1 AND ml_feature_ref IS NOT NULL)",
            name="valid_ml_reference",
        ),
        Index("ix_txn_occurred_at", "occurred_at"),
        Index("ix_txn_customer_occurred", "customer_id", "occurred_at"),
        Index("ix_txn_account_occurred", "account_id", "occurred_at"),
        Index("ix_txn_amount", "amount_minor"),
        Index("ix_txn_type", "transaction_type"),
        Index("ix_txn_country", "country"),
        Index("ix_txn_ml_eligible", "ml_eligible"),
    )


class Investigation(Base):
    __tablename__ = "investigations"

    investigation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Alert(Base):
    __tablename__ = "alerts"

    alert_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigations.investigation_id", ondelete="SET NULL"),
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    escalation_action: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_snapshot_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint(
            "status IN ('open', 'in_review', 'escalated', 'dismissed', 'closed')",
            name="valid_alert_status",
        ),
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(
        ForeignKey("alerts.alert_id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_version: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (Index("ix_alert_events_alert_timestamp", "alert_id", "timestamp"),)
