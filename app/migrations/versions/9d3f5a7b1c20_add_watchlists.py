"""Shared watchlist selections, source snapshots and refresh leases."""

from alembic import op
import sqlalchemy as sa

revision = "9d3f5a7b1c20"
down_revision = "7c2e4f6a8b10"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "registration_links",
        sa.Column("registrations_imported_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_athletes_name", "athletes", ["name"])
    op.create_index(
        "ix_registration_competitors_link_name",
        "registration_link_competitors",
        ["registration_link_id", "athlete_name"],
    )
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("canonical_selection", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_watchlists_expires_at", "watchlists", ["expires_at"])
    op.create_table(
        "watchlist_schedules",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("snapshot", sa.JSON()),
        sa.Column("snapshot_version", sa.Uuid()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("coverage", sa.JSON()),
        sa.Column("discovery", sa.JSON()),
        sa.Column("refresh_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String()),
    )
    slots = op.create_table(
        "watchlist_refresh_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(slots, [{"id": 1}, {"id": 2}])


def downgrade():
    op.drop_table("watchlist_refresh_slots")
    op.drop_table("watchlist_schedules")
    op.drop_table("watchlists")
    op.drop_index(
        "ix_registration_competitors_link_name",
        table_name="registration_link_competitors",
    )
    op.drop_index("ix_athletes_name", table_name="athletes")
    op.drop_column("registration_links", "registrations_imported_at")
