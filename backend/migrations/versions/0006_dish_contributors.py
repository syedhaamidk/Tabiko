"""Credit the dishes people contribute.

`dishes.added_by_user_id` records who typed a dish in, so the person who filled
in a menu can be credited for it. `ON DELETE SET NULL` rather than CASCADE:
deleting an account should not silently delete a menu that other readers now
rely on, and the dish simply becomes unattributed.

The table is recreated through batch_alter_table because SQLite cannot add a
column with a foreign key to a table it is adding one to.

Revision ID: 0006_dish_contributors
Revises: 0005_refresh_tokens
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_dish_contributors"
down_revision: str | None = "0005_refresh_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Postgres adds columns and constraints directly. The recreate below is
        # SQLite-only: it cannot add a column with a foreign key in one step,
        # so the table is copied. Forcing that dance here fails — dropping the
        # primary key is refused while reviews depend on it.
        op.add_column(
            "dishes", sa.Column("added_by_user_id", sa.Integer(), nullable=True)
        )
        op.add_column(
            "dishes",
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_foreign_key(
            "fk_dishes_added_by_user_id_users",
            "dishes",
            "users",
            ["added_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    else:
        with op.batch_alter_table("dishes", recreate="always") as batch_op:
            batch_op.add_column(
                sa.Column("added_by_user_id", sa.Integer(), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "created_at",
                    sa.DateTime(),
                    nullable=False,
                    server_default=sa.func.now(),
                )
            )
            batch_op.create_foreign_key(
                "fk_dishes_added_by_user_id_users",
                "users",
                ["added_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )
    # Server defaults are a migration-time convenience only; the model declares
    # the real default in Python.
    with op.batch_alter_table("dishes") as batch_op:
        batch_op.alter_column("created_at", server_default=None)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(
            "fk_dishes_added_by_user_id_users", "dishes", type_="foreignkey"
        )
        op.drop_column("dishes", "created_at")
        op.drop_column("dishes", "added_by_user_id")
        return

    with op.batch_alter_table("dishes", recreate="always") as batch_op:
        batch_op.drop_constraint("fk_dishes_added_by_user_id_users", type_="foreignkey")
        batch_op.drop_column("created_at")
        batch_op.drop_column("added_by_user_id")
