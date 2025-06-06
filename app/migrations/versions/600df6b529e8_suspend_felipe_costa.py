"""suspend felipe costa

Revision ID: 600df6b529e8
Revises: e4dfc67c1880
Create Date: 2025-03-21 08:46:44.396986

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "600df6b529e8"
down_revision = "e4dfc67c1880"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO suspensions (id, athlete_name, start_date, end_date) VALUES "
            "('716b9475-ac73-4937-83b0-44b902f16d56', 'Cássio Felipe Sousa Costa', '2024-12-13 00:00:00', '2025-12-30 23:59:59')"
        )
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE from suspensions where id = '716b9475-ac73-4937-83b0-44b902f16d56'"
        )
    )
    # ### end Alembic commands ###
