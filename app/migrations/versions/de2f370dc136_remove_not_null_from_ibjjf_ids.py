"""remove not null from ibjjf ids

Revision ID: de2f370dc136
Revises: 66806d2a91d0
Create Date: 2025-01-06 20:40:01.347248

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "de2f370dc136"
down_revision = "66806d2a91d0"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table("athletes", schema=None) as batch_op:
        batch_op.alter_column("ibjjf_id", existing_type=sa.VARCHAR(), nullable=True)

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.alter_column("ibjjf_id", existing_type=sa.VARCHAR(), nullable=True)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table("events", schema=None) as batch_op:
        batch_op.alter_column("ibjjf_id", existing_type=sa.VARCHAR(), nullable=False)

    with op.batch_alter_table("athletes", schema=None) as batch_op:
        batch_op.alter_column("ibjjf_id", existing_type=sa.VARCHAR(), nullable=False)

    # ### end Alembic commands ###
