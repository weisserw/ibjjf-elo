import logging
from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from progress_bar import Bar
from models import Match, Division
from elo import compute_ratings
from current import generate_current_ratings

log = logging.getLogger("ibjjf")


def recompute_all_ratings(
    db: SQLAlchemy,
    gi: bool,
    gender: Optional[str] = None,
    start_date: Optional[datetime] = None,
    score: bool = True,
    rerank: bool = True,
    rerankgi: bool = True,
    reranknogi: bool = True,
    no_tty: bool = False,
) -> int:
    count = 0

    if score:
        query = db.session.query(Match).join(Division).filter(Division.gi == gi)

        if gender is not None:
            query = query.filter(Division.gender == gender)
        if start_date is not None:
            query = query.filter(Match.happened_at >= start_date)

        count = query.count()

        with Bar(
            f'Recomputing athlete {"gi" if gi else "no-gi"} ratings',
            max=count,
            check_tty=False,
            no_tty=no_tty,
        ) as bar:
            for match in query.order_by(Match.happened_at, Match.id):
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
                    red_start_rating,
                    red_end_rating,
                    blue_start_rating,
                    blue_end_rating,
                    red_weight_for_open,
                    blue_weight_for_open,
                    red_rating_note,
                    blue_rating_note,
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
                if red.rating_note != red_rating_note:
                    red.rating_note = red_rating_note
                    changed = True
                if blue.rating_note != blue_rating_note:
                    blue.rating_note = blue_rating_note
                    changed = True
                if match.rated != rated:
                    match.rated = rated
                    changed = True

                if changed:
                    db.session.flush()

    if rerank and (rerankgi or reranknogi):
        if rerankgi and reranknogi:
            desc = "gi/no-gi"
        elif rerankgi:
            desc = "gi"
        else:
            desc = "no-gi"
        log.info(f"Regenerating {desc} ranking board...")
        generate_current_ratings(db, rerankgi, reranknogi)

    return count
