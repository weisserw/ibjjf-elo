"""add medal import audit columns

Revision ID: a14e2f7b9c3d
Revises: 26f5ef66820b
Create Date: 2026-05-17 10:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a14e2f7b9c3d"
down_revision = "26f5ef66820b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("medals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("imported_via", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("imported_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("medals", schema=None) as batch_op:
        batch_op.drop_column("imported_at")
        batch_op.drop_column("imported_via")
