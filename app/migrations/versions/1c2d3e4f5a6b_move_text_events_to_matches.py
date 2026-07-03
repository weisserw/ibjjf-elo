"""move text events to matches

Revision ID: 1c2d3e4f5a6b
Revises: 8c7f2a91e4b3
Create Date: 2026-07-03 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1c2d3e4f5a6b"
down_revision = "8c7f2a91e4b3"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conflict = conn.execute(
        sa.text(
            """
            SELECT mpte.livestream_frame_text_event_id
            FROM match_participant_text_events mpte
            JOIN match_participants mp
                ON mp.id = mpte.match_participant_id
            GROUP BY mpte.livestream_frame_text_event_id
            HAVING COUNT(DISTINCT mp.match_id) > 1
            LIMIT 1
            """
        )
    ).first()
    if conflict:
        raise RuntimeError("Cannot migrate text events with links to multiple matches")

    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.add_column(sa.Column("match_id", sa.UUID(), nullable=True))
        batch_op.create_foreign_key(
            "fk_livestream_frame_text_events_match_id_matches",
            "matches",
            ["match_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_livestream_frame_text_events_match_second",
            ["match_id", "frame_second"],
            unique=False,
        )

    op.execute(
        sa.text(
            """
            UPDATE livestream_frame_text_events
            SET match_id = (
                SELECT mp.match_id
                FROM match_participant_text_events mpte
                JOIN match_participants mp
                    ON mp.id = mpte.match_participant_id
                WHERE mpte.livestream_frame_text_event_id =
                    livestream_frame_text_events.id
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1
                FROM match_participant_text_events mpte
                WHERE mpte.livestream_frame_text_event_id =
                    livestream_frame_text_events.id
            )
            """
        )
    )

    with op.batch_alter_table("match_participant_text_events", schema=None) as batch_op:
        batch_op.drop_index("ix_match_participant_text_events_participant")
        batch_op.drop_index("ix_match_participant_text_events_event")
    op.drop_table("match_participant_text_events")

    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.drop_column("coarse_interval_seconds")

    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.drop_column("needs_review")


def downgrade():
    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "needs_review",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    with op.batch_alter_table("livestream_frame_text_scans", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "coarse_interval_seconds",
                sa.Integer(),
                nullable=False,
                server_default="120",
            )
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

    with op.batch_alter_table("livestream_frame_text_events", schema=None) as batch_op:
        batch_op.drop_index("ix_livestream_frame_text_events_match_second")
        batch_op.drop_constraint(
            "fk_livestream_frame_text_events_match_id_matches",
            type_="foreignkey",
        )
        batch_op.drop_column("match_id")
