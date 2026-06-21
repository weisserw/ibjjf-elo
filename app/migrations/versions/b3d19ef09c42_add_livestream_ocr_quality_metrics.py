"""add livestream OCR quality metrics

Revision ID: b3d19ef09c42
Revises: a8f6d2c4b901
Create Date: 2026-06-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b3d19ef09c42"
down_revision = "a8f6d2c4b901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "known_score_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "score_complete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "clock_detected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.drop_column("clock_detected")
        batch_op.drop_column("score_complete")
        batch_op.drop_column("known_score_count")
