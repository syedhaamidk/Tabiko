"""Following people.

The shortest honest version of "see reviews from people I trust": a follows
table, immediate, no requests and no approval step.

That is a deliberate choice rather than an unfinished one. A request-and-accept
flow needs an inbox, an unread count, a notification endpoint and a settings
screen, and it fails completely in a city where the reader follows five people
who do not follow back -- which is every city, at the scale this is at. Following
someone who does not follow back is not a mistake, it is the normal case, and a
flow that punishes it teaches people not to follow at all.

The unique pair is what makes the whole feature idempotent. Tapping follow twice,
or retrying a request that timed out after the server accepted it, cannot produce
a duplicate row, so `POST` needs no read-before-write and no locking.

The self-follow guard lives here rather than in the endpoint. A row where
`follower_id == followed_id` is meaningless under any interpretation, and a
CHECK constraint is the only place it cannot be written from -- not by this
endpoint, not by a script, not by a future admin tool.

Revision ID: 0009_follows
Revises: 0008_photo_uploads
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_follows"
down_revision: str | None = "0008_photo_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "follower_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "followed_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("follower_id", "followed_id", name="uq_follow_pair"),
        # Following yourself is meaningless, and this is the only place that
        # cannot be written from.
        sa.CheckConstraint("follower_id != followed_id", name="ck_follow_not_self"),
    )
    # "who do I follow" and "who follows me" are the only two questions asked,
    # and both are asked constantly, so both get an index that serves the sort.
    op.create_index(
        "ix_follows_follower_created", "follows", ["follower_id", "created_at"]
    )
    op.create_index("ix_follows_followed", "follows", ["followed_id"])


def downgrade() -> None:
    op.drop_index("ix_follows_followed", table_name="follows")
    op.drop_index("ix_follows_follower_created", table_name="follows")
    op.drop_table("follows")
