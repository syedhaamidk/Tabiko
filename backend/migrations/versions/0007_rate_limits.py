"""Shared rate-limit counters.

The limiter used to keep its windows in each worker process's memory, so with
`--workers 4` a caller got four times the configured allowance -- the limits on
`/auth/login` and `/auth/register` were the ones that mattered most, because
bcrypt makes them expensive enough to be worth attacking, and they were the
easiest to multiply.

Counters now live in the database the app already has. No Redis, no Memcached,
no new service: this is a single-box deployment with one SQLite file on a
volume, and adding infrastructure to fix a counter would have been the larger
change by a wide margin.

The increment is a single atomic statement. A read-then-write would let two
workers each read "9" and each write "10" for what was really the eleventh
request, which is the whole bug in miniature. `INSERT ... ON CONFLICT DO UPDATE
... RETURNING count` is one statement and one row write, so the database
serialises it and the value returned is the true post-increment total.

WAL mode is what makes this tolerable. Readers do not block the writer, so the
counter write does not stall the request that is being rate limited, and the
limiter's own contention is short.

Revision ID: 0007_rate_limits
Revises: 0006_dish_contributors
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_rate_limits"
down_revision: str | None = "0006_dish_contributors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("client_key", sa.String(255), nullable=False),
        # The start of the fixed window, in epoch seconds. Bucketing the window
        # into the row means a second request needs no cleanup pass first, and
        # the primary key alone is enough to keep one row per window.
        sa.Column("window_start", sa.Integer(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("scope", "client_key", "window_start"),
    )
    # The sweep that clears old windows looks up by age alone.
    op.create_index("ix_rate_limits_window_start", "rate_limits", ["window_start"])


def downgrade() -> None:
    op.drop_index("ix_rate_limits_window_start", table_name="rate_limits")
    op.drop_table("rate_limits")
