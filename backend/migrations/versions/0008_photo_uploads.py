"""Reader-uploaded photos for dishes and reviews.

Two nullable URL columns, one on `dishes` and one on `reviews`. The image bytes
are **not** in the database: a photo table would make every restaurant listing
query drag megabytes of blobs through SQLite, and the app already has durable
local storage in the deployment -- the `tabiko-data` volume the compose file
mounts for the database.

Which means the deployment target decides where they go, and this deployment
target has no object store. There is no S3, no GCS, no MinIO in the compose file
and no key configured for any of them. Adding a bucket provider to store a few
food photographs would be a new service, a new credential and a new failure
mode, so the files go on the same volume as the database and are served back
through an API route.

The consequences are stated rather than hidden:

- **The URLs are not durable across a redeploy that discards the volume.** The
  volume is what keeps them. `scripts/backup.py` now covers them, which is what
  makes that survivable.
- **A row can outlive its file.** Deleting a dish does not delete the upload,
  because nothing here owns the file's lifecycle. A sweep is the honest answer
  and is listed as future work.
- **Two boxes would not share uploads.** Same single-file-database caveat as the
  rate limiter. A real object store is what fixes both.

Revision ID: 0008_photo_uploads
Revises: 0007_rate_limits
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_photo_uploads"
down_revision: str | None = "0007_rate_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Deliberately short. These are dish and venue photographs, not a camera roll.
MAX_URL_LENGTH = 500


def upgrade() -> None:
    with op.batch_alter_table("dishes") as batch_op:
        batch_op.add_column(
            sa.Column("image_url", sa.String(MAX_URL_LENGTH), nullable=True)
        )
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.add_column(
            sa.Column("image_url", sa.String(MAX_URL_LENGTH), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_column("image_url")
    with op.batch_alter_table("dishes") as batch_op:
        batch_op.drop_column("image_url")
