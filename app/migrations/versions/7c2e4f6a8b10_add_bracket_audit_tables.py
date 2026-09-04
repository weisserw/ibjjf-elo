"""add bracket audit tables

Revision ID: 7c2e4f6a8b10
Revises: 0862fbdb2381
Create Date: 2026-09-03 19:00:00

"""

from alembic import op
import sqlalchemy as sa


revision = "7c2e4f6a8b10"
down_revision = "0862fbdb2381"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bracket_audit_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("background_task_id", sa.UUID(), nullable=True),
        sa.Column("registration_link_id", sa.UUID(), nullable=True),
        sa.Column("tournament_id", sa.String(), nullable=False),
        sa.Column("tournament_name", sa.String(), nullable=False),
        sa.Column("gi", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("registration_source_at", sa.DateTime(), nullable=True),
        sa.Column("seeding_reference_date", sa.DateTime(), nullable=True),
        sa.Column("medal_cutoff", sa.DateTime(), nullable=True),
        sa.Column("total_category_count", sa.Integer(), nullable=False),
        sa.Column("discovered_category_count", sa.Integer(), nullable=False),
        sa.Column("processed_category_count", sa.Integer(), nullable=False),
        sa.Column("error_category_count", sa.Integer(), nullable=False),
        sa.Column("clean_category_count", sa.Integer(), nullable=False),
        sa.Column("criteria_mismatch_count", sa.Integer(), nullable=False),
        sa.Column("tie_only_count", sa.Integer(), nullable=False),
        sa.Column("layout_mismatch_count", sa.Integer(), nullable=False),
        sa.Column("missing_table_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_category_count", sa.Integer(), nullable=False),
        sa.Column("fatal_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["background_task_id"], ["background_tasks.id"]),
        sa.ForeignKeyConstraint(["registration_link_id"], ["registration_links.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("bracket_audit_runs", schema=None) as batch_op:
        batch_op.create_index("ix_bracket_audit_runs_created_at", ["created_at"])
        batch_op.create_index("ix_bracket_audit_runs_status", ["status"])
        batch_op.create_index("ix_bracket_audit_runs_tournament", ["tournament_id"])

    op.create_table(
        "bracket_audit_categories",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("external_category_id", sa.String(), nullable=True),
        sa.Column("category_url", sa.String(), nullable=False),
        sa.Column("gender", sa.String(), nullable=True),
        sa.Column("age", sa.String(), nullable=True),
        sa.Column("belt", sa.String(), nullable=True),
        sa.Column("weight", sa.String(), nullable=True),
        sa.Column("raw_gender", sa.String(), nullable=True),
        sa.Column("raw_age", sa.String(), nullable=True),
        sa.Column("raw_belt", sa.String(), nullable=True),
        sa.Column("raw_weight", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cache_saved_at", sa.DateTime(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("seeding_variant", sa.String(), nullable=True),
        sa.Column("normalized_headers_json", sa.Text(), nullable=True),
        sa.Column("unmapped_headers_json", sa.Text(), nullable=True),
        sa.Column("official_competitor_count", sa.Integer(), nullable=True),
        sa.Column("parsed_bracket_size", sa.Integer(), nullable=True),
        sa.Column("theoretical_bracket_size", sa.Integer(), nullable=True),
        sa.Column("ranking_status", sa.String(), nullable=True),
        sa.Column("reconciliation_status", sa.String(), nullable=True),
        sa.Column("criteria_status", sa.String(), nullable=True),
        sa.Column("layout_status", sa.String(), nullable=True),
        sa.Column("matched_competitor_count", sa.Integer(), nullable=False),
        sa.Column("mismatched_competitor_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_row_count", sa.Integer(), nullable=False),
        sa.Column("differing_criteria_count", sa.Integer(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["bracket_audit_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "category_url", name="uq_bracket_audit_run_url"),
    )
    with op.batch_alter_table("bracket_audit_categories", schema=None) as batch_op:
        batch_op.create_index("ix_bracket_audit_categories_run", ["run_id"])
        batch_op.create_index("ix_bracket_audit_categories_status", ["status"])


def downgrade():
    with op.batch_alter_table("bracket_audit_categories", schema=None) as batch_op:
        batch_op.drop_index("ix_bracket_audit_categories_status")
        batch_op.drop_index("ix_bracket_audit_categories_run")
    op.drop_table("bracket_audit_categories")
    with op.batch_alter_table("bracket_audit_runs", schema=None) as batch_op:
        batch_op.drop_index("ix_bracket_audit_runs_tournament")
        batch_op.drop_index("ix_bracket_audit_runs_status")
        batch_op.drop_index("ix_bracket_audit_runs_created_at")
    op.drop_table("bracket_audit_runs")
