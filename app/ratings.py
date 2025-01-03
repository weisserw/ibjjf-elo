import logging
from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from progress.bar import Bar
from models import Match, MatchParticipant, Division
from elo import compute_ratings
from current import generate_current_ratings

log = logging.getLogger("ibjjf")


def recompute_all_ratings(
    db: SQLAlchemy,
    gi: bool,
    gender: Optional[str] = None,
    age: Optional[str] = None,
    start_date: Optional[datetime] = None,
    rerank: bool = True,
) -> int:
    query = (
        db.session.query(Match)
        .join(MatchParticipant)
        .join(Division)
        .filter(Division.gi == gi)
    )

    if gender is not None:
        query = query.filter(Division.gender == gender)
    if age is not None:
        query = query.filter(Division.age == age)
    if start_date is not None:
        query = query.filter(Match.happened_at >= start_date)

    count = query.count() // 2

    with Bar(
        f'Recomputing athlete {"gi" if gi else "no-gi"} ratings', max=count
    ) as bar:
        for match in query.order_by(Match.happened_at, Match.id).all():
            bar.next()

            if len(match.participants) != 2:
                log.info(
                    f"Match {match.id} has {len(match.participants)} participants, skipping"
                )
                continue

            count += 1

            red, blue = match.participants
            (
                rated,
                unrated_reason,
                red_start_rating,
                red_end_rating,
                blue_start_rating,
                blue_end_rating,
                red_weight_for_open,
                blue_weight_for_open,
            ) = compute_ratings(
                db,
                match.event_id,
                match.id,
                match.division,
                match.happened_at,
                red.athlete_id,
                red.winner,
                red.note,
                blue.athlete_id,
                blue.winner,
                blue.note,
            )

            changed = False

            if red.start_rating != red_start_rating:
                red.start_rating = red_start_rating
                changed = True
            if red.end_rating != red_end_rating:
                red.end_rating = red_end_rating
                changed = True
            if blue.start_rating != blue_start_rating:
                blue.start_rating = blue_start_rating
                changed = True
            if blue.end_rating != blue_end_rating:
                blue.end_rating = blue_end_rating
                changed = True
            if red.weight_for_open != red_weight_for_open:
                red.weight_for_open = red_weight_for_open
                changed = True
            if blue.weight_for_open != blue_weight_for_open:
                blue.weight_for_open = blue_weight_for_open
                changed = True
            if match.rated != rated:
                match.rated = rated
                changed = True
            if match.unrated_reason != unrated_reason:
                match.unrated_reason = unrated_reason
                changed = True

            if changed:
                db.session.flush()

    if rerank:
        log.info("Regenerating ranking board...")
        generate_current_ratings(db)

    return count
