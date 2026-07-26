"""phase 4 investigation execution trace

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-26 11:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from backend.app.data.types import UTCDateTime

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "investigation_runs",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("investigation_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=False),
        sa.Column("plan_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", UTCDateTime(length=32), nullable=False),
        sa.Column("completed_at", UTCDateTime(length=32), nullable=True),
        sa.Column("execution_summary_json", sa.JSON(), nullable=True),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name=op.f("ck_investigation_runs_valid_investigation_run_status"),
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.investigation_id"],
            name=op.f("fk_investigation_runs_investigation_id_investigations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_investigation_runs")),
    )
    op.create_index(
        "ix_investigation_runs_investigation",
        "investigation_runs",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        "ix_investigation_runs_request",
        "investigation_runs",
        ["request_id"],
        unique=False,
    )
    op.create_table(
        "investigation_step_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("step_id", sa.String(length=64), nullable=False),
        sa.Column("tool", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("event", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("tool_result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", UTCDateTime(length=32), nullable=False),
        sa.CheckConstraint(
            "event IN ('planned', 'running', 'succeeded', 'failed', 'skipped', 'timed_out')",
            name=op.f("ck_investigation_step_events_valid_step_event"),
        ),
        sa.CheckConstraint(
            "attempt >= 1",
            name=op.f("ck_investigation_step_events_positive_attempt"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["investigation_runs.run_id"],
            name=op.f("fk_investigation_step_events_run_id_investigation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_investigation_step_events")),
    )
    op.create_index(
        "ix_step_events_run_created",
        "investigation_step_events",
        ["run_id", "created_at"],
        unique=False,
    )
    with op.batch_alter_table("investigations") as batch_op:
        batch_op.create_check_constraint(
            "valid_investigation_status",
            "status IN ('running', 'completed', 'partial', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("investigations") as batch_op:
        batch_op.drop_constraint("valid_investigation_status", type_="check")
    op.drop_index("ix_step_events_run_created", table_name="investigation_step_events")
    op.drop_table("investigation_step_events")
    op.drop_index("ix_investigation_runs_request", table_name="investigation_runs")
    op.drop_index("ix_investigation_runs_investigation", table_name="investigation_runs")
    op.drop_table("investigation_runs")
