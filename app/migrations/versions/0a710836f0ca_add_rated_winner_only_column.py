"""add rated_winner_only column

Revision ID: 0a710836f0ca
Revises: 324d24f6ead6
Create Date: 2025-01-31 10:33:26.323944

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0a710836f0ca"
down_revision = "324d24f6ead6"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rated_winner_only", sa.Boolean(), nullable=True))

    op.execute("UPDATE matches SET rated_winner_only = False")

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.alter_column(
            "rated_winner_only", existing_type=sa.BOOLEAN(), nullable=False
        )

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_column("rated_winner_only")

    # ### end Alembic commands ###
