"""add youtube match videos table

Revision ID: 59b7c8d9e012
Revises: 3b8a6d4f2c1e
Create Date: 2026-06-16 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "59b7c8d9e012"
down_revision = "3b8a6d4f2c1e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "youtube_match_videos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("youtube_video_id", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("thumbnail_url", sa.String(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(), nullable=False),
        sa.Column("ignored", sa.Boolean(), nullable=False),
        sa.Column("imported_match_id", sa.UUID(), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["imported_match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "youtube_video_id", name="uq_youtube_match_videos_youtube_video_id"
        ),
    )
    with op.batch_alter_table("youtube_match_videos", schema=None) as batch_op:
        batch_op.create_index(
            "ix_youtube_match_videos_ignored", ["ignored"], unique=False
        )
        batch_op.create_index(
            "ix_youtube_match_videos_imported_match_id",
            ["imported_match_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_youtube_match_videos_published_at", ["published_at"], unique=False
        )
        batch_op.create_index(
            "ix_youtube_match_videos_scraped_at", ["scraped_at"], unique=False
        )


def downgrade():
    with op.batch_alter_table("youtube_match_videos", schema=None) as batch_op:
        batch_op.drop_index("ix_youtube_match_videos_scraped_at")
        batch_op.drop_index("ix_youtube_match_videos_published_at")
        batch_op.drop_index("ix_youtube_match_videos_imported_match_id")
        batch_op.drop_index("ix_youtube_match_videos_ignored")
    op.drop_table("youtube_match_videos")
