"""Suspend Rider Zuchi Samelo do Amaral.

Revision ID: f2a4c6e8b0d1
Revises: d4f6a8c0e2b4
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa


revision = "f2a4c6e8b0d1"
down_revision = "d4f6a8c0e2b4"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO suspensions (id, athlete_name, start_date, end_date, reason, suspending_org) VALUES "
            "('af892b6f-49a7-40a1-8e26-3cd24724dfda', 'Rider Zuchi Samelo do Amaral', "
            "'2024-08-23 00:00:00', '2029-06-30 23:59:59', "
            "'Drostanolone and 19-norandrosterone', 'USADA')"
        )
    )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM suspensions WHERE id = "
            "'af892b6f-49a7-40a1-8e26-3cd24724dfda'"
        )
    )
