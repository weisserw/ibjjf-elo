"""revert livestream OCR schema

Revision ID: f0d9c2e4a6b7
Revises: c6e2a51f0d8b
Create Date: 2026-06-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f0d9c2e4a6b7"
down_revision = "c6e2a51f0d8b"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_ocr_readings_archive_second")
        batch_op.drop_index("ix_livestream_frame_ocr_readings_segment_id")
        batch_op.drop_index("ix_livestream_frame_ocr_readings_archive_id")
    op.drop_table("livestream_frame_ocr_readings")

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
        batch_op.alter_column(
            "processed_frame_count",
            new_column_name="uploaded_frame_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "last_processed_second",
            new_column_name="last_uploaded_second",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )

    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "s3_prefix",
                sa.String(),
                nullable=False,
                server_default="",
            )
        )
        batch_op.alter_column(
            "s3_prefix",
            existing_type=sa.String(),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "processed_frame_count",
            new_column_name="uploaded_frame_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "last_processed_second",
            new_column_name="last_uploaded_second",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_archives", schema=None) as batch_op:
        batch_op.alter_column(
            "uploaded_frame_count",
            new_column_name="processed_frame_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "last_uploaded_second",
            new_column_name="last_processed_second",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.drop_column("s3_prefix")

    with op.batch_alter_table(
        "livestream_frame_capture_segments", schema=None
    ) as batch_op:
        batch_op.alter_column(
            "uploaded_frame_count",
            new_column_name="processed_frame_count",
            existing_type=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "last_uploaded_second",
            new_column_name="last_processed_second",
            existing_type=sa.Integer(),
            existing_nullable=True,
        )
        batch_op.drop_column("batch_uploaded_at")
        batch_op.drop_column("batch_s3_key")
        batch_op.drop_column("sampled_frame_count")

    op.create_table(
        "livestream_frame_ocr_readings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("archive_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("frame_second", sa.Integer(), nullable=False),
        sa.Column("frame_index", sa.Integer(), nullable=False),
        sa.Column("video_offset_seconds", sa.Float(), nullable=False),
        sa.Column("ocr_engine", sa.String(), nullable=False),
        sa.Column("overlay_style", sa.String(), nullable=True),
        sa.Column("clock", sa.String(), nullable=True),
        sa.Column("red_points", sa.Integer(), nullable=True),
        sa.Column("red_advantages", sa.Integer(), nullable=True),
        sa.Column("red_penalties", sa.Integer(), nullable=True),
        sa.Column("blue_points", sa.Integer(), nullable=True),
        sa.Column("blue_advantages", sa.Integer(), nullable=True),
        sa.Column("blue_penalties", sa.Integer(), nullable=True),
        sa.Column("victory", sa.Boolean(), nullable=False),
        sa.Column("victory_text", sa.Text(), nullable=True),
        sa.Column("scoreboard_text", sa.Text(), nullable=True),
        sa.Column("timer_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "known_score_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "score_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "clock_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("red_athlete_name", sa.Text(), nullable=True),
        sa.Column("red_team_name", sa.Text(), nullable=True),
        sa.Column("blue_athlete_name", sa.Text(), nullable=True),
        sa.Column("blue_team_name", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["archive_id"], ["livestream_frame_archives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["livestream_frame_capture_segments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_id",
            "frame_second",
            name="uq_livestream_frame_ocr_readings_archive_second",
        ),
    )
    with op.batch_alter_table("livestream_frame_ocr_readings", schema=None) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_ocr_readings_archive_id",
            ["archive_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_ocr_readings_segment_id",
            ["segment_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_ocr_readings_archive_second",
            ["archive_id", "frame_second"],
            unique=False,
        )
