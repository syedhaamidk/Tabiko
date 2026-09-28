"""Google sign-in: link a Google identity to a reader account.

A `google_sub` holds the stable subject claim Google issues for an account in
this project. It is unique and nullable: most readers arrive by email and
password and never have one.

Linking is by verified email, not by trust. A Google account whose email is
unverified proves nothing about that address, so it can neither create nor
claim an account here. A verified one may do either: a matching email gets
the sub attached (the reader keeps their reviews, saves and follows), and a
new address gets a fresh account with no password. There is deliberately no
unlink endpoint — removing the only credential on an account would lock the
reader out, and removing a second one is a support conversation, not a button.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_google_sub"
down_revision: str | None = "0009_follows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A plain ADD COLUMN: nullable, no default, no constraint the database must
    # enforce at write time — so no batch recreation on SQLite and no drama on
    # PostgreSQL. The uniqueness lives in a separate index for the same reason.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("google_sub", sa.String(255), nullable=True))
        batch_op.create_index("ix_users_google_sub", ["google_sub"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_google_sub")
        batch_op.drop_column("google_sub")
