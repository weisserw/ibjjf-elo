"""Remove crowded observations whose actual changes are minor abbreviations.

Revision ID: c3e5a7b9d1f3
Revises: b2d4f6a8c0e2
"""

from collections import Counter
import re

from alembic import op
import sqlalchemy as sa


revision = "c3e5a7b9d1f3"
down_revision = "b2d4f6a8c0e2"
branch_labels = None
depends_on = None


MINOR_ABBREVIATION = re.compile(r"^[^\W\d_]\.\s+\S+$", re.UNICODE)


def _names(value):
    return [name.strip() for name in (value or "").split(";")]


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, old_name, new_name FROM result_rename_observations "
            "WHERE evidence = 'crowded_result_slot'"
        )
    ).mappings()
    false_positive_ids = []
    for row in rows:
        remaining_old = Counter(name.casefold() for name in _names(row["old_name"]))
        changed_new_names = []
        for name in _names(row["new_name"]):
            key = name.casefold()
            if remaining_old[key]:
                remaining_old[key] -= 1
            else:
                changed_new_names.append(name)
        if changed_new_names and all(
            MINOR_ABBREVIATION.fullmatch(name) for name in changed_new_names
        ):
            false_positive_ids.append(row["id"])
    for observation_id in false_positive_ids:
        connection.execute(
            sa.text("DELETE FROM result_rename_observations WHERE id = :id"),
            {"id": observation_id},
        )


def downgrade():
    # Deleted false-positive observations cannot be reconstructed reliably.
    pass
