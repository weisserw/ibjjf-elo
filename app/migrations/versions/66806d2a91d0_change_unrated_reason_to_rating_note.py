"""change unrated reason to rating note

Revision ID: 66806d2a91d0
Revises: 7694f7204bec
Create Date: 2025-01-04 10:46:19.609358

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '66806d2a91d0'
down_revision = '7694f7204bec'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###

    with op.batch_alter_table('match_participants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('rating_note', sa.Text(), nullable=True))

    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.drop_column('unrated_reason')

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###e)

    with op.batch_alter_table('matches', schema=None) as batch_op:
        batch_op.add_column(sa.Column('unrated_reason', sa.VARCHAR(), nullable=True))

    with op.batch_alter_table('match_participants', schema=None) as batch_op:
        batch_op.drop_column('rating_note')

    # ### end Alembic commands ###
