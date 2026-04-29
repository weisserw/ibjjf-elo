"""add flo mat links table

Revision ID: f2c7ad981d29
Revises: 1b8307290539
Create Date: 2026-04-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f2c7ad981d29"
down_revision = "1b8307290539"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "flo_mat_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("mat_number", sa.Integer(), nullable=False),
        sa.Column("link", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("flo_mat_links", schema=None) as batch_op:
        batch_op.create_index("ix_flo_mat_links_event_id", ["event_id"], unique=False)
        batch_op.create_index(
            "ix_flo_mat_links_event_mat",
            ["event_id", "mat_number"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("flo_mat_links", schema=None) as batch_op:
        batch_op.drop_index("ix_flo_mat_links_event_mat")
        batch_op.drop_index("ix_flo_mat_links_event_id")

    op.drop_table("flo_mat_links")
