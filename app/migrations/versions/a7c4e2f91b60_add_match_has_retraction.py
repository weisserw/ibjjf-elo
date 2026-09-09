"""add match has retraction

Revision ID: a7c4e2f91b60
Revises: 9d3f5a7b1c20
Create Date: 2026-09-08 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "a7c4e2f91b60"
down_revision = "9d3f5a7b1c20"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("has_retraction", sa.Boolean(), nullable=True))


def downgrade():
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_column("has_retraction")
