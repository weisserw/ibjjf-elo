"""expand media coverage types and add portuguese flag

Revision ID: 8d4c7f6a91b2
Revises: 2f364c8f5a91
Create Date: 2026-06-10 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8d4c7f6a91b2"
down_revision = "2f364c8f5a91"
branch_labels = None
depends_on = None


OLD_COVERAGE_TYPE_CHECK = "coverage_type IN ('feature', 'news', 'video')"
NEW_COVERAGE_TYPE_CHECK = (
    "coverage_type IN ("
    "'feature', 'news', 'video', 'podcast', "
    "'highlight', 'technique', 'interview', 'breakdown'"
    ")"
)


def upgrade():
    with op.batch_alter_table("athlete_media_coverage", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_athlete_media_coverage_type",
            type_="check",
        )
        batch_op.add_column(
            sa.Column(
                "portuguese",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_check_constraint(
            "ck_athlete_media_coverage_type",
            NEW_COVERAGE_TYPE_CHECK,
        )


def downgrade():
    op.execute(
        """
        UPDATE athlete_media_coverage
        SET coverage_type = 'news'
        WHERE coverage_type NOT IN ('feature', 'news', 'video')
        """
    )

    with op.batch_alter_table("athlete_media_coverage", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_athlete_media_coverage_type",
            type_="check",
        )
        batch_op.drop_column("portuguese")
        batch_op.create_check_constraint(
            "ck_athlete_media_coverage_type",
            OLD_COVERAGE_TYPE_CHECK,
        )
