"""Index canonical first initial and surname for IBJJF abbreviated names.

Revision ID: d7e12a6c4b09
Revises: c5a1e8d42f70
"""

from alembic import op
import sqlalchemy as sa

revision = "d7e12a6c4b09"
down_revision = "c5a1e8d42f70"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "athletes", sa.Column("normalized_initial_surname", sa.String(), nullable=True)
    )
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        # normalized_name is already lowercase, accent folded, stripped to
        # letters/numbers, and collapsed to single spaces. Derive every key in
        # one database statement instead of loading and updating all athletes
        # through Python.
        connection.execute(
            sa.text(
                """
            UPDATE athletes
            SET normalized_initial_surname =
                left(normalized_name, 1) || ' ' ||
                regexp_replace(normalized_name, '^.* ', '')
            WHERE normalized_name LIKE '% %'
        """
            )
        )
    elif connection.dialect.name == "sqlite":
        # SQLite has no reverse() or equivalent last-token function. This CTE
        # walks the already-normalized words, then performs one set-based update.
        connection.execute(
            sa.text(
                """
            WITH RECURSIVE name_words(id, normalized_name, rest, last_word) AS (
                SELECT id, normalized_name, trim(normalized_name), ''
                FROM athletes
                WHERE normalized_name LIKE '% %'
                UNION ALL
                SELECT
                    id,
                    normalized_name,
                    CASE WHEN instr(rest, ' ') = 0 THEN ''
                         ELSE ltrim(substr(rest, instr(rest, ' ') + 1)) END,
                    CASE WHEN instr(rest, ' ') = 0 THEN rest
                         ELSE substr(rest, 1, instr(rest, ' ') - 1) END
                FROM name_words
                WHERE rest <> ''
            ),
            keys AS (
                SELECT id, substr(normalized_name, 1, 1) || ' ' || last_word AS key
                FROM name_words
                WHERE rest = ''
            )
            UPDATE athletes
            SET normalized_initial_surname = (
                SELECT key FROM keys WHERE keys.id = athletes.id
            )
            WHERE id IN (SELECT id FROM keys)
        """
            )
        )
    else:
        raise RuntimeError(
            "Unsupported database for normalized initial/surname backfill: "
            f"{connection.dialect.name}"
        )
    op.create_index(
        "ix_athletes_initial_surname", "athletes", ["normalized_initial_surname", "id"]
    )


def downgrade():
    op.drop_index("ix_athletes_initial_surname", table_name="athletes")
    op.drop_column("athletes", "normalized_initial_surname")
