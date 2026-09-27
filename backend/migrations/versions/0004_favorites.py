"""Saved places.

A reader can keep a shortlist of places. The unique pair of user and restaurant
is what makes saving idempotent, and the composite index serves the only query
this table ever answers: one reader's saves, newest first.

Revision ID: 0004_favorites
Revises: 0003_venue_types
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_favorites"
down_revision: str | None = "0003_venue_types"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name=op.f("fk_favorites_restaurant_id_restaurants"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_favorites_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_favorites")),
        sa.UniqueConstraint(
            "user_id", "restaurant_id", name="uq_favorite_user_restaurant"
        ),
    )
    op.create_index(
        "ix_favorites_user_created",
        "favorites",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_favorites_user_created", table_name="favorites")
    op.drop_table("favorites")
