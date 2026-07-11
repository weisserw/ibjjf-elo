"""add bad flag to livestream frame archives

Revision ID: 4f8c1a7d2e90
Revises: 8d4f6a2c1b03
Create Date: 2026-07-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "4f8c1a7d2e90"
down_revision = "8d4f6a2c1b03"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_bad",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.drop_column("is_bad")
