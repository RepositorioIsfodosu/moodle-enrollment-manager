"""Durable job leases, scheduling and reconciliation metadata."""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    for column in [
        sa.Column("lease_owner", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("runtime", sa.JSON(), nullable=False, server_default="{}"),
    ]:
        op.add_column("enrollment_jobs", column)
    op.create_index("ix_enrollment_jobs_lease_until", "enrollment_jobs", ["lease_until"])
    for column in [
        sa.Column("validation_record_id", sa.Uuid(), sa.ForeignKey("validation_records.id")),
        sa.Column("error_code", sa.String(100)),
        sa.Column("reconciles_record_id", sa.Uuid(), sa.ForeignKey("enrollment_records.id")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reconciliation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    ]:
        op.add_column("enrollment_records", column)


def downgrade():
    for name in [
        "reconciles_record_id",
        "next_attempt_at",
        "reconciliation_count",
        "retry_count",
        "error_code",
        "validation_record_id",
    ]:
        op.drop_column("enrollment_records", name)
    op.drop_index("ix_enrollment_jobs_lease_until", table_name="enrollment_jobs")
    for name in ["runtime", "dispatched_at", "next_run_at", "lease_until", "lease_owner"]:
        op.drop_column("enrollment_jobs", name)
