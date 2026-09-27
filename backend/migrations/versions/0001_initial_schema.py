"""Create the initial hardened application schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

restaurant_type = sa.Enum(
    "cafe",
    "family_restaurant",
    "fine_dine",
    "cloud_kitchen",
    "darshini_qsr",
    "bar_microbrewery",
    "food_court_stall",
    "unclassified",
    name="restauranttype",
)
verification_tier = sa.Enum(
    "unverified",
    "checked_in",
    "order_confirmed",
    name="verificationtier",
)


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=True, unique=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("raw_cuisine_tag", sa.String(255), nullable=True),
        sa.Column("cuisine_tags", sa.String(500), nullable=True),
        sa.Column("type_tag", restaurant_type, nullable=False),
        sa.Column("dietary_flags", sa.String(255), nullable=True),
        sa.Column("price_tier", sa.Integer(), nullable=True),
        sa.Column("hygiene_score", sa.Float(), nullable=True),
        sa.Column("theme_id", sa.String(50), nullable=True),
        sa.Column("menu_last_confirmed", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("price_tier >= 1 AND price_tier <= 4", name="ck_price_tier"),
        sa.CheckConstraint(
            "hygiene_score >= 0 AND hygiene_score <= 5", name="ck_hygiene_score"
        ),
    )
    op.create_index("ix_restaurants_name", "restaurants", ["name"])

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("is_founding_reviewer", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "dishes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tags", sa.String(255), nullable=True),
        sa.Column("avg_rating", sa.Float(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("review_count >= 0", name="ck_dish_review_count"),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_dish_restaurant_name"),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "restaurant_id",
            sa.Integer(),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dish_id",
            sa.Integer(),
            sa.ForeignKey("dishes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_request_id", sa.String(36), nullable=True),
        sa.Column("rating", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("verification_tier", verification_tier, nullable=False),
        sa.Column("fraud_flag", sa.Boolean(), nullable=False),
        sa.Column("fraud_reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_review_rating"),
        sa.UniqueConstraint(
            "user_id", "client_request_id", name="uq_review_user_request"
        ),
    )
    op.create_index(
        "ix_reviews_restaurant_created",
        "reviews",
        ["restaurant_id", "created_at"],
    )
    op.create_index("ix_reviews_user_created", "reviews", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("reviews")
    op.drop_table("dishes")
    op.drop_table("users")
    op.drop_index("ix_restaurants_name", table_name="restaurants")
    op.drop_table("restaurants")
    verification_tier.drop(op.get_bind(), checkfirst=True)
    restaurant_type.drop(op.get_bind(), checkfirst=True)
