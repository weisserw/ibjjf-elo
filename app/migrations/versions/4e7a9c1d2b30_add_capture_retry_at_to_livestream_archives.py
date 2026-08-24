"""add capture retry timestamp to livestream archives

Revision ID: 4e7a9c1d2b30
Revises: daf9892dfd70
Create Date: 2026-08-24 01:30:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4e7a9c1d2b30"
down_revision = "daf9892dfd70"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.add_column(sa.Column("capture_retry_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            "ix_livestream_frame_archives_capture_retry_at",
            ["capture_retry_at"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_archives_capture_retry_at")
        batch_op.drop_column("capture_retry_at")
