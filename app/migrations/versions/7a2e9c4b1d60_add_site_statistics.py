"""add site statistics

Revision ID: 7a2e9c4b1d60
Revises: 4f8c1a7d2e90
Create Date: 2026-07-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "7a2e9c4b1d60"
down_revision = "4f8c1a7d2e90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_statistics",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("site_statistics")
