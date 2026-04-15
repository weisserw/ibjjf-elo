"""suspend Roosevelt Souza

Revision ID: 1b8307290539
Revises: dc06d1a5a17b
Create Date: 2026-04-15 18:45:06.517970

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "1b8307290539"
down_revision = "dc06d1a5a17b"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO suspensions (id, athlete_name, start_date, end_date, reason, suspending_org) VALUES "
            "('41994e0e-d172-42b6-9649-2d30f67cd162', 'Roosevelt Pereira Lima de Sousa', '2025-12-12 00:00:00', '2029-01-13 23:59:59', 'Meldonium', 'USADA')"
        )
    )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE from suspensions where id = '41994e0e-d172-42b6-9649-2d30f67cd162'"
        )
    )
