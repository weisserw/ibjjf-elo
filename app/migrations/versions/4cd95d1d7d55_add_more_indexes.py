"""add more indexes

Revision ID: 4cd95d1d7d55
Revises: bbc2b9cc8af2
Create Date: 2025-03-29 22:16:43.184035

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4cd95d1d7d55"
down_revision = "bbc2b9cc8af2"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("athletes", schema=None) as batch_op:
        batch_op.drop_index("ix_athletes_normalized_name")
        batch_op.create_index(
            "ix_athletes_normalized_name_covering",
            ["normalized_name", "id"],
            unique=False,
        )

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.create_index(
            "ix_match_participants_losers",
            ["match_id", "athlete_id"],
            unique=False,
            postgresql_where=sa.text("winner = false"),
        )
        batch_op.create_index(
            "ix_match_participants_winners",
            ["match_id", "athlete_id"],
            unique=False,
            postgresql_where=sa.text("winner = true"),
        )

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_index("ix_matches_division_id_covering")
        batch_op.create_index(
            "ix_matches_division_id_covering",
            ["division_id", "happened_at", "id"],
            unique=False,
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_index("ix_matches_division_id_covering")
        batch_op.create_index(
            "ix_matches_division_id_covering", ["division_id", "id"], unique=False
        )

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.drop_index("ix_match_participants_winners")
        batch_op.drop_index("ix_match_participants_losers")

    with op.batch_alter_table("divisions", schema=None) as batch_op:
        batch_op.drop_index("ix_divisions_age_covering")

    with op.batch_alter_table("athletes", schema=None) as batch_op:
        batch_op.drop_index("ix_athletes_normalized_name_covering")
        batch_op.create_index(
            "ix_athletes_normalized_name", ["normalized_name"], unique=False
        )

    # ### end Alembic commands ###
