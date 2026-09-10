"""merge duplicate 2024 no-gi Brasileiros events

Revision ID: c5a1e8d42f70
Revises: a7c4e2f91b60
Create Date: 2026-09-09

"""

from alembic import op
import sqlalchemy as sa


revision = "c5a1e8d42f70"
down_revision = "a7c4e2f91b60"
branch_labels = None
depends_on = None


ARCHIVE_NAME = "Brazilian Nationals No Gi 2024 (Archive)"
MEDALS_ONLY_NAME = "Brazilian National Jiu-Jitsu No-Gi Championship 2024"


def upgrade():
    bind = op.get_bind()
    events = sa.table(
        "events",
        sa.column("id"),
        sa.column("name"),
        sa.column("medals_only"),
    )
    medals = sa.table(
        "medals",
        sa.column("id"),
        sa.column("event_id"),
        sa.column("division_id"),
        sa.column("athlete_id"),
        sa.column("place"),
    )
    matches = sa.table("matches", sa.column("event_id"))

    archive_id = bind.execute(
        sa.select(events.c.id).where(events.c.name == ARCHIVE_NAME)
    ).scalar()
    medals_only_id = bind.execute(
        sa.select(events.c.id).where(events.c.name == MEDALS_ONLY_NAME)
    ).scalar()
    if archive_id is None or medals_only_id is None or archive_id == medals_only_id:
        return

    # Be idempotent with databases where an overlapping medal was already
    # copied to the archive event. The table's unique key is
    # (event_id, division_id, athlete_id).
    # Resolve the small collision set in Python to keep the migration portable
    # across PostgreSQL and SQLite.
    source_rows = bind.execute(
        sa.select(
            medals.c.id,
            medals.c.division_id,
            medals.c.athlete_id,
            medals.c.place,
        ).where(medals.c.event_id == medals_only_id)
    ).all()
    for medal_id, division_id, athlete_id, place in source_rows:
        collision = bind.execute(
            sa.select(medals.c.id, medals.c.place).where(
                medals.c.event_id == archive_id,
                medals.c.division_id == division_id,
                medals.c.athlete_id == athlete_id,
            )
        ).first()
        if collision is not None:
            target_id, target_place = collision
            if place < target_place:
                bind.execute(
                    sa.update(medals)
                    .where(medals.c.id == target_id)
                    .values(place=place)
                )
            bind.execute(sa.delete(medals).where(medals.c.id == medal_id))

    bind.execute(
        sa.update(medals)
        .where(medals.c.event_id == medals_only_id)
        .values(event_id=archive_id)
    )
    bind.execute(
        sa.update(matches)
        .where(matches.c.event_id == medals_only_id)
        .values(event_id=archive_id)
    )
    bind.execute(
        sa.update(events).where(events.c.id == archive_id).values(medals_only=False)
    )
    bind.execute(sa.delete(events).where(events.c.id == medals_only_id))


def downgrade():
    # The original split cannot be reconstructed reliably after rows have been
    # consolidated, so this cleanup is intentionally irreversible.
    pass
