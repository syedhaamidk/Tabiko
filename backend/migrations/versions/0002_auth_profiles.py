"""Add authentication, reviewer profiles, and restaurant experience fields.

Revision ID: 0002_auth_profiles
Revises: 0001_initial
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_auth_profiles"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

noise_level = sa.Enum("quiet", "moderate", "loud", "unknown", name="noiselevel")
reviewer_type = sa.Enum(
    "normal", "food_critic", "cuisine_specialist", name="reviewertype"
)


def upgrade() -> None:
    # On PostgreSQL these types have to exist before any column can use them,
    # and batch-mode ADD COLUMN does not create them the way CREATE TABLE does.
    # SQLite has no enum types at all (it stores VARCHAR), so this is a no-op
    # there by dialect, not by flag — nothing about the SQLite path changes.
    if op.get_bind().dialect.name == "postgresql":
        noise_level.create(op.get_bind(), checkfirst=True)
        reviewer_type.create(op.get_bind(), checkfirst=True)

    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.add_column(
            sa.Column(
                "noise_level",
                noise_level,
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.add_column(sa.Column("good_for", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column("accessibility_flags", sa.String(255), nullable=True)
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "reviewer_type",
                reviewer_type,
                nullable=False,
                server_default="normal",
            )
        )
        batch_op.add_column(
            sa.Column("cuisine_specialty", sa.String(255), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "is_critic_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index("ix_users_email", ["email"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_email")
        batch_op.drop_column("is_critic_verified")
        batch_op.drop_column("cuisine_specialty")
        batch_op.drop_column("reviewer_type")
        batch_op.drop_column("is_admin")
        batch_op.drop_column("password_hash")

    with op.batch_alter_table("restaurants") as batch_op:
        batch_op.drop_column("accessibility_flags")
        batch_op.drop_column("good_for")
        batch_op.drop_column("noise_level")

    reviewer_type.drop(op.get_bind(), checkfirst=True)
    noise_level.drop(op.get_bind(), checkfirst=True)
