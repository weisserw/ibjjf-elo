"""add division_size to matches

Revision ID: 3b8a6d4f2c1e
Revises: 8d4c7f6a91b2
Create Date: 2026-06-13 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "3b8a6d4f2c1e"
down_revision = "8d4c7f6a91b2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("division_size", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE matches
        SET division_size = (
            SELECT MAX(m2.match_number)
            FROM matches AS m2
            WHERE m2.event_id = matches.event_id
              AND m2.division_id = matches.division_id
              AND m2.match_number IS NOT NULL
        )
        WHERE match_number IS NOT NULL
        """
    )


def downgrade():
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_column("division_size")
