"""add unique constraint to medals on event/division/athlete

Revision ID: b7d1f4a82e91
Revises: a14e2f7b9c3d
Create Date: 2026-05-18 10:00:00.000000

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "b7d1f4a82e91"
down_revision = "a14e2f7b9c3d"
branch_labels = None
depends_on = None


def upgrade():
    # Remove any existing duplicate medals before applying the constraint,
    # keeping the row with the best (lowest) place per athlete/division/event.
    op.execute(
        """
        DELETE FROM medals
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY event_id, division_id, athlete_id
                           ORDER BY place ASC, imported_at ASC NULLS LAST, id
                       ) AS rn
                FROM medals
            ) ranked
            WHERE rn > 1
        )
        """
    )

    with op.batch_alter_table("medals", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_medals_event_division_athlete",
            ["event_id", "division_id", "athlete_id"],
        )


def downgrade():
    with op.batch_alter_table("medals", schema=None) as batch_op:
        batch_op.drop_constraint("uq_medals_event_division_athlete", type_="unique")
