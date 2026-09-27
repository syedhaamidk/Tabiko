"""Widen the restaurant type vocabulary.

SQLite stores the enum as a VARCHAR with a CHECK constraint, so the table is
recreated through batch_alter_table to relax the constraint. Existing rows keep
their current type_tag.

Revision ID: 0003_venue_types
Revises: 0002_auth_profiles
Create Date: 2026-09-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_venue_types"
down_revision: str | None = "0002_auth_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_TYPES = (
    "cafe",
    "family_restaurant",
    "fine_dine",
    "cloud_kitchen",
    "darshini_qsr",
    "bar_microbrewery",
    "food_court_stall",
    "unclassified",
)

WIDENED_TYPES = LEGACY_TYPES + (
    "canteen",
    "dhaba",
    "street_stall",
    "hotel_restaurant",
    "takeaway",
)


def upgrade() -> None:
    widened = sa.Enum(*WIDENED_TYPES, name="restauranttype")
    with op.batch_alter_table("restaurants", recreate="always") as batch_op:
        batch_op.alter_column(
            "type_tag",
            existing_type=sa.Enum(*LEGACY_TYPES, name="restauranttype"),
            type_=widened,
            existing_nullable=False,
        )


def downgrade() -> None:
    legacy = sa.Enum(*LEGACY_TYPES, name="restauranttype")
    with op.batch_alter_table("restaurants", recreate="always") as batch_op:
        batch_op.alter_column(
            "type_tag",
            existing_type=sa.Enum(*WIDENED_TYPES, name="restauranttype"),
            type_=legacy,
            existing_nullable=False,
        )
