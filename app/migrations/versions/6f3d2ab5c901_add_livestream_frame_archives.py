"""add livestream frame archives

Revision ID: 6f3d2ab5c901
Revises: 59b7c8d9e012
Create Date: 2026-06-19 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6f3d2ab5c901"
down_revision = "59b7c8d9e012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "livestream_frame_archives",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("youtube_video_id", sa.String(), nullable=False),
        sa.Column("canonical_url", sa.String(), nullable=False),
        sa.Column("s3_prefix", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("frame_rate", sa.Float(), nullable=False),
        sa.Column("image_format", sa.String(), nullable=False),
        sa.Column("jpeg_quality", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("expected_frame_count", sa.Integer(), nullable=True),
        sa.Column("uploaded_frame_count", sa.Integer(), nullable=False),
        sa.Column("last_uploaded_second", sa.Integer(), nullable=True),
        sa.Column("format_id", sa.String(), nullable=True),
        sa.Column("format_note", sa.String(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_fps", sa.Float(), nullable=True),
        sa.Column("video_codec", sa.String(), nullable=True),
        sa.Column("audio_codec", sa.String(), nullable=True),
        sa.Column("tbr", sa.Float(), nullable=True),
        sa.Column("protocol", sa.String(), nullable=True),
        sa.Column("yt_dlp_version", sa.String(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "youtube_video_id", name="uq_livestream_frame_archives_youtube_video_id"
        ),
    )
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_archives_status", ["status"], unique=False
        )

    op.create_table(
        "livestream_frame_capture_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("archive_id", sa.UUID(), nullable=False),
        sa.Column("start_second", sa.Integer(), nullable=False),
        sa.Column("end_second", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_frame_count", sa.Integer(), nullable=False),
        sa.Column("last_uploaded_second", sa.Integer(), nullable=True),
        sa.Column("background_task_id", sa.UUID(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["archive_id"], ["livestream_frame_archives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["background_task_id"], ["background_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_id",
            "start_second",
            "end_second",
            name="uq_livestream_frame_capture_segments_range",
        ),
    )
    with op.batch_alter_table(
        "livestream_frame_capture_segments", schema=None
    ) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_capture_segments_archive_id",
            ["archive_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_capture_segments_status", ["status"], unique=False
        )
        batch_op.create_index(
            "ix_livestream_frame_capture_segments_background_task_id",
            ["background_task_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_capture_segments_archive_start",
            ["archive_id", "start_second"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table(
        "livestream_frame_capture_segments", schema=None
    ) as batch_op:
        batch_op.drop_index("ix_livestream_frame_capture_segments_archive_start")
        batch_op.drop_index("ix_livestream_frame_capture_segments_background_task_id")
        batch_op.drop_index("ix_livestream_frame_capture_segments_status")
        batch_op.drop_index("ix_livestream_frame_capture_segments_archive_id")
    op.drop_table("livestream_frame_capture_segments")

    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_archives_status")
    op.drop_table("livestream_frame_archives")
