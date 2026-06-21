"""add livestream OCR name fields

Revision ID: c6e2a51f0d8b
Revises: b3d19ef09c42
Create Date: 2026-06-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6e2a51f0d8b"
down_revision = "b3d19ef09c42"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("red_athlete_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("red_team_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("blue_athlete_name", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("blue_team_name", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.drop_column("blue_team_name")
        batch_op.drop_column("blue_athlete_name")
        batch_op.drop_column("red_team_name")
        batch_op.drop_column("red_athlete_name")
