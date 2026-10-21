"""Add revocable sessions, normalize email identities and seed fixed application roles."""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Abort rather than silently merge pre-existing identities.
    duplicate = connection.execute(
        sa.text(
            "SELECT lower(trim(email)) FROM users GROUP BY lower(trim(email)) HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError("Correos duplicados tras normalización; resolver antes de migrar")
    op.execute("UPDATE users SET email = lower(trim(email))")
    op.create_check_constraint("normalized_email", "users", "email = lower(trim(email))")
    op.create_table(
        "auth_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_sessions_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_sessions_token_hash")),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    for name in ("administrador", "operador", "supervisor", "consulta"):
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, name) VALUES (:id, :name) ON CONFLICT (name) DO NOTHING"
            ),
            {"id": uuid.uuid4(), "name": name},
        )


def downgrade():
    op.drop_table("auth_sessions")
    op.drop_constraint(op.f("ck_users_normalized_email"), "users", type_="check")
    # Preserve role assignments and audit history; a downgrade must not delete them.
