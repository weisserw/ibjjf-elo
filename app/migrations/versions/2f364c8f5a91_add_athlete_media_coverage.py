"""add athlete media coverage

Revision ID: 2f364c8f5a91
Revises: b7d1f4a82e91
Create Date: 2026-06-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "2f364c8f5a91"
down_revision = "b7d1f4a82e91"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "athlete_media_coverage",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("athlete_id", sa.UUID(), nullable=False),
        sa.Column("covered_at", sa.Date(), nullable=False),
        sa.Column("coverage_type", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "coverage_type IN ('feature', 'news', 'video', 'podcast')",
            name="ck_athlete_media_coverage_type",
        ),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "athlete_id",
            "url",
            name="uq_athlete_media_coverage_athlete_url",
        ),
    )
    with op.batch_alter_table("athlete_media_coverage", schema=None) as batch_op:
        batch_op.create_index(
            "ix_athlete_media_coverage_athlete_date",
            ["athlete_id", "covered_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_athlete_media_coverage_athlete_id",
            ["athlete_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("athlete_media_coverage", schema=None) as batch_op:
        batch_op.drop_index("ix_athlete_media_coverage_athlete_id")
        batch_op.drop_index("ix_athlete_media_coverage_athlete_date")

    op.drop_table("athlete_media_coverage")
