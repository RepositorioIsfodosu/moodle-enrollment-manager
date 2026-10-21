"""Require explicit evidence before interpreting a filtered membership list as complete."""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "role_approvals",
        sa.Column(
            "full_enrollment_visibility",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("role_approvals", "full_enrollment_visibility")
