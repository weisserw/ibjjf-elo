"""add livestream custom crop sizes

Revision ID: 7c3e5a1b9d02
Revises: 4b2c9d8e7f10
Create Date: 2026-07-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "7c3e5a1b9d02"
down_revision = "4b2c9d8e7f10"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.add_column(sa.Column("preview_s3_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("preview_content_type", sa.String(), nullable=True)
        )
        for crop in ("scoreboard", "timer"):
            for field in ("x", "y", "width", "height"):
                batch_op.add_column(
                    sa.Column(f"{crop}_crop_{field}", sa.Float(), nullable=True)
                )


def downgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        for crop in ("timer", "scoreboard"):
            for field in ("height", "width", "y", "x"):
                batch_op.drop_column(f"{crop}_crop_{field}")
        batch_op.drop_column("preview_content_type")
        batch_op.drop_column("preview_s3_key")
