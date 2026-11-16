"""Add anonymous match access sessions and shared usage counters."""

from alembic import op
import sqlalchemy as sa

revision = "a3b5c7d9e1f2"
down_revision = "f2a4c6e8b0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "match_access_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("burst_bucket", sa.BigInteger(), nullable=False),
        sa.Column("burst_requests", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_match_access_sessions_expires_at", "match_access_sessions", ["expires_at"]
    )


def downgrade():
    op.drop_index(
        "ix_match_access_sessions_expires_at", table_name="match_access_sessions"
    )
    op.drop_table("match_access_sessions")
