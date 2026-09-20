"""Track when result rename observations are applied.

Revision ID: f9a2c4d6e8b0
Revises: e8f1a2b3c4d5
"""

from alembic import op
import sqlalchemy as sa


revision = "f9a2c4d6e8b0"
down_revision = "e8f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "result_rename_observations",
        sa.Column("applied_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("result_rename_observations", "applied_at")
