"""add athlete match covering index

Revision ID: daf9892dfd70
Revises: 91781f63e73f
Create Date: 2026-08-22 22:15:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "daf9892dfd70"
down_revision = "91781f63e73f"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_match_participants_athlete_match_id",
            "match_participants",
            ["athlete_id", "match_id"],
            unique=False,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_match_participants_athlete_match_id",
            table_name="match_participants",
        )
