"""add livestream scoreboard state

Revision ID: d9a7e4f3c2b1
Revises: b2a4d8c9f103
Create Date: 2026-06-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d9a7e4f3c2b1"
down_revision = "b2a4d8c9f103"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("scoreboard_state", sa.String(), nullable=True))


def downgrade():
    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.drop_column("scoreboard_state")
