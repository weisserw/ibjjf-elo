"""Add result snapshot provenance and rename observations.

Revision ID: e8f1a2b3c4d5
Revises: d7e12a6c4b09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e8f1a2b3c4d5"
down_revision = "d7e12a6c4b09"
branch_labels = None
depends_on = None


def upgrade():
    uuid_type = postgresql.UUID(as_uuid=True)
    op.create_table(
        "result_snapshots",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("manifest_path", sa.String(), nullable=True),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_result_snapshots_started_at", "result_snapshots", ["started_at"]
    )
    with op.batch_alter_table("result_medals") as batch:
        batch.add_column(sa.Column("occurrence_key", sa.String(), nullable=True))
        batch.add_column(
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("snapshot_id", uuid_type, nullable=True))
        batch.create_foreign_key(
            "fk_result_medals_snapshot_id", "result_snapshots", ["snapshot_id"], ["id"]
        )
        batch.create_index(
            "ix_result_medals_occurrence_key", ["occurrence_key"], unique=True
        )
        batch.create_index("ix_result_medals_active", ["active"])
    op.create_table(
        "result_rename_observations",
        sa.Column("id", uuid_type, nullable=False),
        sa.Column("snapshot_id", uuid_type, nullable=False),
        sa.Column("result_medal_id", uuid_type, nullable=True),
        sa.Column("athlete_id", uuid_type, nullable=True),
        sa.Column("slot_key", sa.String(), nullable=False),
        sa.Column("old_name", sa.String(), nullable=True),
        sa.Column("new_name", sa.String(), nullable=True),
        sa.Column("old_team", sa.String(), nullable=True),
        sa.Column("new_team", sa.String(), nullable=True),
        sa.Column("change_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["athlete_id"], ["athletes.id"]),
        sa.ForeignKeyConstraint(["result_medal_id"], ["result_medals.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["result_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "slot_key",
            "old_name",
            "new_name",
            name="uq_result_rename_observation",
        ),
    )
    op.create_index(
        "ix_result_rename_observations_snapshot_id",
        "result_rename_observations",
        ["snapshot_id"],
    )
    op.create_index(
        "ix_result_rename_observations_status",
        "result_rename_observations",
        ["status"],
    )


def downgrade():
    op.drop_index(
        "ix_result_rename_observations_status",
        table_name="result_rename_observations",
    )
    op.drop_index(
        "ix_result_rename_observations_snapshot_id",
        table_name="result_rename_observations",
    )
    op.drop_table("result_rename_observations")
    with op.batch_alter_table("result_medals") as batch:
        batch.drop_index("ix_result_medals_active")
        batch.drop_index("ix_result_medals_occurrence_key")
        batch.drop_constraint("fk_result_medals_snapshot_id", type_="foreignkey")
        batch.drop_column("snapshot_id")
        batch.drop_column("active")
        batch.drop_column("occurrence_key")
    op.drop_index("ix_result_snapshots_started_at", table_name="result_snapshots")
    op.drop_table("result_snapshots")
