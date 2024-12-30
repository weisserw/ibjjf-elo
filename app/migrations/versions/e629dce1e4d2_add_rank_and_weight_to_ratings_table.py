"""add rank and weight to ratings table

Revision ID: e629dce1e4d2
Revises: 05baa9af70fd
Create Date: 2024-12-28 13:59:48.697430

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e629dce1e4d2"
down_revision = "05baa9af70fd"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("athlete_ratings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("weight", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("rank", sa.Integer(), nullable=True))
        batch_op.drop_index("ix_athlete_ratings_all")
        batch_op.create_index(
            "ix_athlete_ratings_all",
            ["gender", "age", "belt", "gi", "weight"],
            unique=False,
        )
        batch_op.drop_constraint(
            "uq_athlete_ratings_athlete_gender_age_gi", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_athlete_ratings_athlete_gender_age_gi",
            ["athlete_id", "gender", "age", "gi", "weight"],
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("athlete_ratings", schema=None) as batch_op:
        batch_op.drop_constraint(
            "uq_athlete_ratings_athlete_gender_age_gi", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_athlete_ratings_athlete_gender_age_gi",
            ["athlete_id", "gender", "age", "gi"],
        )
        batch_op.drop_index("ix_athlete_ratings_all")
        batch_op.create_index(
            "ix_athlete_ratings_all", ["gender", "age", "belt", "gi"], unique=False
        )
        batch_op.drop_column("rank")
        batch_op.drop_column("weight")

    # ### end Alembic commands ###
