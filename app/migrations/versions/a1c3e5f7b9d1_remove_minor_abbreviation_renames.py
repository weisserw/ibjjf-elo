"""Remove minor privacy abbreviations from rename observations.

Revision ID: a1c3e5f7b9d1
Revises: f9a2c4d6e8b0
"""

from alembic import op


revision = "a1c3e5f7b9d1"
down_revision = "f9a2c4d6e8b0"
branch_labels = None
depends_on = None


def upgrade():
    # The strict minor display form is one initial, a period, and one surname
    # token. These rows are privacy-format transitions, not canonical renames.
    op.execute(
        """
        DELETE FROM result_rename_observations
        WHERE new_name LIKE '_. %'
          AND new_name NOT LIKE '_. % %'
        """
    )


def downgrade():
    # Deleted false-positive observations cannot be reconstructed reliably.
    pass
