"""add composite matches index

Revision ID: 91781f63e73f
Revises: 7a2e9c4b1d60
Create Date: 2026-08-22 21:06:17.732409

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "91781f63e73f"
down_revision = "7a2e9c4b1d60"
branch_labels = None
depends_on = None


def upgrade():
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_matches_event_division_id",
            "matches",
            ["event_id", "division_id", "id"],
            unique=False,
        )


def downgrade():
    with op.get_context().autocommit_block():
        op.drop_index("ix_matches_event_division_id", table_name="matches")
