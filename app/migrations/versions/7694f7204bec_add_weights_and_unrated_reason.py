"""add weights and unrated reason

Revision ID: 7694f7204bec
Revises: e629dce1e4d2
Create Date: 2024-12-29 18:14:21.889223

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "7694f7204bec"
down_revision = "e629dce1e4d2"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.add_column(sa.Column("weight_for_open", sa.String(), nullable=True))

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("unrated_reason", sa.String(), nullable=True))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_column("unrated_reason")

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.drop_column("weight_for_open")

    # ### end Alembic commands ###
