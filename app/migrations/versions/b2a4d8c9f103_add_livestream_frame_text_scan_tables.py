"""add livestream frame text scan tables

Revision ID: b2a4d8c9f103
Revises: f0d9c2e4a6b7
Create Date: 2026-06-26 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2a4d8c9f103"
down_revision = "f0d9c2e4a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "livestream_frame_text_scans",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("archive_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parser_profile", sa.String(), nullable=False),
        sa.Column("score_engine", sa.String(), nullable=False),
        sa.Column("name_engine", sa.String(), nullable=True),
        sa.Column("coarse_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("total_segment_count", sa.Integer(), nullable=False),
        sa.Column("processed_segment_count", sa.Integer(), nullable=False),
        sa.Column("last_processed_second", sa.Integer(), nullable=True),
        sa.Column("background_task_id", sa.UUID(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["archive_id"], ["livestream_frame_archives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["background_task_id"], ["background_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_id", name="uq_livestream_frame_text_scans_archive"
        ),
    )
    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_text_scans_background_task_id",
            ["background_task_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_scans_status", ["status"], unique=False
        )

    op.create_table(
        "livestream_frame_text_scan_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("archive_id", sa.UUID(), nullable=False),
        sa.Column("capture_segment_id", sa.UUID(), nullable=False),
        sa.Column("start_second", sa.Integer(), nullable=False),
        sa.Column("end_second", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("last_processed_second", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["capture_segment_id"],
            ["livestream_frame_capture_segments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["livestream_frame_text_scans.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scan_id",
            "capture_segment_id",
            name="uq_livestream_frame_text_scan_segments_capture",
        ),
    )
    with op.batch_alter_table(
        "livestream_frame_text_scan_segments", schema=None
    ) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_text_scan_segments_archive_id",
            ["archive_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_scan_segments_archive_start",
            ["archive_id", "start_second"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_scan_segments_background_task_id",
            ["background_task_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_scan_segments_scan_id",
            ["scan_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_scan_segments_status",
            ["status"],
            unique=False,
        )

    op.create_table(
        "livestream_frame_text_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column("archive_id", sa.UUID(), nullable=False),
        sa.Column("scan_segment_id", sa.UUID(), nullable=False),
        sa.Column("capture_segment_id", sa.UUID(), nullable=False),
        sa.Column("frame_second", sa.Integer(), nullable=False),
        sa.Column("top_points", sa.Integer(), nullable=True),
        sa.Column("top_advantages", sa.Integer(), nullable=True),
        sa.Column("top_penalties", sa.Integer(), nullable=True),
        sa.Column("bottom_points", sa.Integer(), nullable=True),
        sa.Column("bottom_advantages", sa.Integer(), nullable=True),
        sa.Column("bottom_penalties", sa.Integer(), nullable=True),
        sa.Column("timer_state", sa.String(), nullable=True),
        sa.Column("timer_value", sa.String(), nullable=True),
        sa.Column("top_athlete_name", sa.Text(), nullable=True),
        sa.Column("top_team_name", sa.Text(), nullable=True),
        sa.Column("bottom_athlete_name", sa.Text(), nullable=True),
        sa.Column("bottom_team_name", sa.Text(), nullable=True),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("score_engine", sa.String(), nullable=True),
        sa.Column("name_engine", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["archive_id"], ["livestream_frame_archives.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["capture_segment_id"],
            ["livestream_frame_capture_segments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"], ["livestream_frame_text_scans.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["scan_segment_id"],
            ["livestream_frame_text_scan_segments.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "archive_id",
            "frame_second",
            name="uq_livestream_frame_text_events_archive_second",
        ),
    )
    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_livestream_frame_text_events_archive_id",
            ["archive_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_events_archive_second",
            ["archive_id", "frame_second"],
            unique=False,
        )
        batch_op.create_index(
            "ix_livestream_frame_text_events_scan_id", ["scan_id"], unique=False
        )
        batch_op.create_index(
            "ix_livestream_frame_text_events_scan_segment_id",
            ["scan_segment_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_text_events_scan_segment_id")
        batch_op.drop_index("ix_livestream_frame_text_events_scan_id")
        batch_op.drop_index("ix_livestream_frame_text_events_archive_second")
        batch_op.drop_index("ix_livestream_frame_text_events_archive_id")
    op.drop_table("livestream_frame_text_events")

    with op.batch_alter_table(
        "livestream_frame_text_scan_segments", schema=None
    ) as batch_op:
        batch_op.drop_index("ix_livestream_frame_text_scan_segments_status")
        batch_op.drop_index("ix_livestream_frame_text_scan_segments_scan_id")
        batch_op.drop_index("ix_livestream_frame_text_scan_segments_background_task_id")
        batch_op.drop_index("ix_livestream_frame_text_scan_segments_archive_start")
        batch_op.drop_index("ix_livestream_frame_text_scan_segments_archive_id")
    op.drop_table("livestream_frame_text_scan_segments")

    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_text_scans_status")
        batch_op.drop_index("ix_livestream_frame_text_scans_background_task_id")
    op.drop_table("livestream_frame_text_scans")
