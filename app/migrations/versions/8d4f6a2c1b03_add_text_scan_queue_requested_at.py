"""add text scan queue requested at

Revision ID: 8d4f6a2c1b03
Revises: 7c3e5a1b9d02
Create Date: 2026-07-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "8d4f6a2c1b03"
down_revision = "7c3e5a1b9d02"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("queue_requested_at", sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.drop_column("queue_requested_at")
