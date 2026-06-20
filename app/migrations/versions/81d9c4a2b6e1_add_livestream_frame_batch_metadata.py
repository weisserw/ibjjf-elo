"""add livestream frame batch metadata

Revision ID: 81d9c4a2b6e1
Revises: 6f3d2ab5c901
Create Date: 2026-06-20 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "81d9c4a2b6e1"
down_revision = "6f3d2ab5c901"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        "livestream_frame_capture_segments", schema=None
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "sampled_frame_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("batch_s3_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("batch_uploaded_at", sa.DateTime(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table(
        "livestream_frame_capture_segments", schema=None
    ) as batch_op:
        batch_op.drop_column("batch_uploaded_at")
        batch_op.drop_column("batch_s3_key")
        batch_op.drop_column("sampled_frame_count")
