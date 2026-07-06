"""add livestream archive queue requested at

Revision ID: 4b2c9d8e7f10
Revises: 1c2d3e4f5a6b
Create Date: 2026-07-06 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4b2c9d8e7f10"
down_revision = "1c2d3e4f5a6b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("queue_requested_at", sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.drop_column("queue_requested_at")
