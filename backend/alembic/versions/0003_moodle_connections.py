"""Connection verification metadata and history; no credentials are created or converted."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(20), server_default="unverified", nullable=False),
        sa.Column("configuration_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("next_probe_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(50)),
        sa.Column("site_metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("available_functions", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("latency_ms", sa.Integer()),
    ):
        op.add_column("moodle_connections", column)
    op.execute("UPDATE moodle_connections SET status = 'disabled' WHERE active = false")
    op.create_check_constraint(
        "status",
        "moodle_connections",
        "status IN ('unverified','verified','limited','error','disabled')",
    )
    op.create_table(
        "moodle_connection_checks",
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("available_functions", sa.JSON(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["connection_id"], ["moodle_connections.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('verified','limited','error')",
            name=op.f("ck_moodle_connection_checks_status"),
        ),
    )
    op.create_index(
        "ix_moodle_connection_checks_connection_id", "moodle_connection_checks", ["connection_id"]
    )


def downgrade():
    op.drop_table("moodle_connection_checks")
    op.drop_constraint(op.f("ck_moodle_connections_status"), "moodle_connections", type_="check")
    for name in (
        "description",
        "status",
        "configuration_version",
        "last_verified_at",
        "next_probe_at",
        "last_error_code",
        "site_metadata",
        "available_functions",
        "latency_ms",
    ):
        op.drop_column("moodle_connections", name)
