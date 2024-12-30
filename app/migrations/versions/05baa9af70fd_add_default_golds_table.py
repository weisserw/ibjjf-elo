"""Add default_golds table

Revision ID: 05baa9af70fd
Revises: 437b007233f4
Create Date: 2024-12-25 23:14:12.400334

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "05baa9af70fd"
down_revision = "437b007233f4"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "default_golds",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("happened_at", sa.DateTime(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("division_id", sa.UUID(), nullable=False),
        sa.Column("athlete_id", sa.UUID(), nullable=False),
        sa.Column("team_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["athlete_id"],
            ["athletes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["division_id"],
            ["divisions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("default_golds", schema=None) as batch_op:
        batch_op.create_index(
            "ix_default_golds_athlete_id", ["athlete_id"], unique=False
        )
        batch_op.create_index(
            "ix_default_golds_division_id", ["division_id"], unique=False
        )
        batch_op.create_index("ix_default_golds_event_id", ["event_id"], unique=False)
        batch_op.create_index(
            "ix_default_golds_happened_at", ["happened_at"], unique=False
        )
        batch_op.create_index("ix_default_golds_team_id", ["team_id"], unique=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("default_golds", schema=None) as batch_op:
        batch_op.drop_index("ix_default_golds_team_id")
        batch_op.drop_index("ix_default_golds_happened_at")
        batch_op.drop_index("ix_default_golds_event_id")
        batch_op.drop_index("ix_default_golds_division_id")
        batch_op.drop_index("ix_default_golds_athlete_id")

    op.drop_table("default_golds")
    # ### end Alembic commands ###
