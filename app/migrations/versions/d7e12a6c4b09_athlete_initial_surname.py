"""Index canonical first initial and surname for IBJJF abbreviated names.

Revision ID: d7e12a6c4b09
Revises: c5a1e8d42f70
"""

from alembic import op
import sqlalchemy as sa

from normalize import normalize

revision = "d7e12a6c4b09"
down_revision = "c5a1e8d42f70"
branch_labels = None
depends_on = None


def _key(name):
    words = normalize(name or "").split()
    if len(words) < 2:
        return None
    return f"{words[0][0]} {words[-1]}"


def upgrade():
    op.add_column("athletes", sa.Column("normalized_initial_surname", sa.String(), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, name FROM athletes")).all()
    statement = sa.text(
        "UPDATE athletes SET normalized_initial_surname = :key WHERE id = :id"
    )
    for athlete_id, name in rows:
        connection.execute(statement, {"id": athlete_id, "key": _key(name)})
    op.create_index("ix_athletes_initial_surname", "athletes", ["normalized_initial_surname", "id"])


def downgrade():
    op.drop_index("ix_athletes_initial_surname", table_name="athletes")
    op.drop_column("athletes", "normalized_initial_surname")
