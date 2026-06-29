"""add OCR match links

Revision ID: 8c7f2a91e4b3
Revises: d9a7e4f3c2b1
Create Date: 2026-06-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8c7f2a91e4b3"
down_revision = "d9a7e4f3c2b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("video_start_offset_seconds", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_match_time_seconds", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("final_top_points", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("final_top_advantages", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_top_penalties", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_bottom_points", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_bottom_advantages", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("final_bottom_penalties", sa.Integer(), nullable=True)
        )

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("scoreboard_position", sa.String(), nullable=True)
        )

    op.create_table(
        "match_participant_text_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("match_participant_id", sa.UUID(), nullable=False),
        sa.Column("livestream_frame_text_event_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["livestream_frame_text_event_id"],
            ["livestream_frame_text_events.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["match_participant_id"],
            ["match_participants.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "match_participant_id",
            "livestream_frame_text_event_id",
            name="uq_match_participant_text_events_pair",
        ),
    )
    with op.batch_alter_table("match_participant_text_events", schema=None) as batch_op:
        batch_op.create_index(
            "ix_match_participant_text_events_event",
            ["livestream_frame_text_event_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_match_participant_text_events_participant",
            ["match_participant_id"],
            unique=False,
        )


def downgrade():
    with op.batch_alter_table("match_participant_text_events", schema=None) as batch_op:
        batch_op.drop_index("ix_match_participant_text_events_participant")
        batch_op.drop_index("ix_match_participant_text_events_event")
    op.drop_table("match_participant_text_events")

    with op.batch_alter_table("match_participants", schema=None) as batch_op:
        batch_op.drop_column("scoreboard_position")

    with op.batch_alter_table("matches", schema=None) as batch_op:
        batch_op.drop_column("final_bottom_penalties")
        batch_op.drop_column("final_bottom_advantages")
        batch_op.drop_column("final_bottom_points")
        batch_op.drop_column("final_top_penalties")
        batch_op.drop_column("final_top_advantages")
        batch_op.drop_column("final_top_points")
        batch_op.drop_column("final_match_time_seconds")
        batch_op.drop_column("video_start_offset_seconds")
