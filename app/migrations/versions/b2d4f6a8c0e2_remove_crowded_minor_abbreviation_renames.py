"""Remove crowded minor privacy abbreviations from rename observations.

Revision ID: b2d4f6a8c0e2
Revises: a1c3e5f7b9d1
"""

import re

from alembic import op
import sqlalchemy as sa


revision = "b2d4f6a8c0e2"
down_revision = "a1c3e5f7b9d1"
branch_labels = None
depends_on = None


MINOR_ABBREVIATION = re.compile(r"^[^\W\d_]\.\s+\S+$", re.UNICODE)


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, new_name FROM result_rename_observations "
            "WHERE evidence = 'crowded_result_slot'"
        )
    ).mappings()
    false_positive_ids = []
    for row in rows:
        names = [name.strip() for name in (row["new_name"] or "").split(";")]
        if names and all(MINOR_ABBREVIATION.fullmatch(name) for name in names):
            false_positive_ids.append(row["id"])
    for observation_id in false_positive_ids:
        connection.execute(
            sa.text("DELETE FROM result_rename_observations WHERE id = :id"),
            {"id": observation_id},
        )


def downgrade():
    # Deleted false-positive observations cannot be reconstructed reliably.
    pass
