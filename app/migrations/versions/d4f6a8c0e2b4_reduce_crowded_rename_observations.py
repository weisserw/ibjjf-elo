"""Reduce crowded observations to their actual unmatched names.

Revision ID: d4f6a8c0e2b4
Revises: c3e5a7b9d1f3
"""

from collections import Counter

from alembic import op
import sqlalchemy as sa


revision = "d4f6a8c0e2b4"
down_revision = "c3e5a7b9d1f3"
branch_labels = None
depends_on = None


def _names(value):
    return [name.strip() for name in (value or "").split(";") if name.strip()]


def _unmatched(old_value, new_value):
    old_names = _names(old_value)
    new_names = _names(new_value)
    remaining_new = Counter(name.casefold() for name in new_names)
    unmatched_old = []
    for name in old_names:
        key = name.casefold()
        if remaining_new[key]:
            remaining_new[key] -= 1
        else:
            unmatched_old.append(name)
    remaining_old = Counter(name.casefold() for name in old_names)
    unmatched_new = []
    for name in new_names:
        key = name.casefold()
        if remaining_old[key]:
            remaining_old[key] -= 1
        else:
            unmatched_new.append(name)
    return unmatched_old, unmatched_new


def upgrade():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, old_name, new_name FROM result_rename_observations "
            "WHERE status = 'pending' AND evidence = 'crowded_result_slot'"
        )
    ).mappings()
    for row in rows:
        unmatched_old, unmatched_new = _unmatched(row["old_name"], row["new_name"])
        if not unmatched_old or not unmatched_new:
            connection.execute(
                sa.text("DELETE FROM result_rename_observations WHERE id = :id"),
                {"id": row["id"]},
            )
            continue
        values = {
            "id": row["id"],
            "old_name": "; ".join(unmatched_old),
            "new_name": "; ".join(unmatched_new),
            "change_type": (
                "renamed"
                if len(unmatched_old) == len(unmatched_new) == 1
                else "uncertain"
            ),
            "evidence": (
                "crowded_slot_unique_delta"
                if len(unmatched_old) == len(unmatched_new) == 1
                else "crowded_result_slot"
            ),
        }
        connection.execute(
            sa.text(
                "UPDATE result_rename_observations "
                "SET old_name = :old_name, new_name = :new_name, "
                "change_type = :change_type, evidence = :evidence "
                "WHERE id = :id"
            ),
            values,
        )


def downgrade():
    # Removed unchanged names and deletion-only observations cannot be restored.
    pass
