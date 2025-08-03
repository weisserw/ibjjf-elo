import logging
from typing import Optional
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

from progress_bar import Bar
from models import Match, Division, Suspension, Athlete, MatchParticipant
from elo import compute_ratings
from current import generate_current_ratings
from normalize import normalize
from constants import TEEN_1, TEEN_2, TEEN_3

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
    rank_previous_date: Optional[datetime] = None,
    athlete_id: Optional[str] = None,
    teens: bool = False,
) -> None:
    if score:
        query = db.session.query(Match).join(Division).filter(Division.gi == gi)

        if gender is not None:
            query = query.filter(Division.gender == gender)
        if start_date is not None:
            query = query.filter(Match.happened_at >= start_date)
        if teens:
            query = query.filter(Division.age.in_([TEEN_1, TEEN_2, TEEN_3]))

        if athlete_id is not None:
            subquery = (
                db.session.query(Match.id)
                .join(MatchParticipant)
                .filter(MatchParticipant.athlete_id == uuid.UUID(athlete_id))
                .subquery()
            )
            query = query.filter(Match.id.in_(subquery.select()))

        total = query.count()

        suspensions = db.session.query(Suspension)
        suspensions_by_id = {}
        for suspension in suspensions:
            athlete = (
                db.session.query(Athlete)
                .filter(Athlete.normalized_name == normalize(suspension.athlete_name))
                .first()
            )
            if athlete is not None:
                suspensions_by_id[athlete.id] = suspension

        with Bar(
            f'Recomputing athlete {"gi" if gi else "no-gi"} ratings',
            max=total,
            check_tty=False,
            no_tty=True,
        ) as bar:
            for match in query.order_by(Match.happened_at, Match.id).yield_per(100):
                bar.next()

                if len(match.participants) != 2:
                    log.info(
                        f"Match {match.id} has {len(match.participants)} participants, skipping"
                    )
                    continue

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
                    red_start_match_count,
                    red_end_match_count,
                    blue_start_match_count,
                    blue_end_match_count,
                ) = compute_ratings(
                    db,
                    match.event_id,
                    match.id,
                    match.division,
                    match.happened_at,
                    match.rated_winner_only,
                    red.athlete_id,
                    red.winner,
                    red.note,
                    blue.athlete_id,
                    blue.winner,
                    blue.note,
                    suspensions_by_id,
                )

                changed = False

                if athlete_id is None or athlete_id == str(red.athlete_id):
                    if red.start_rating != red_start_rating:
                        red.start_rating = red_start_rating
                        changed = True
                    if red.end_rating != red_end_rating:
                        red.end_rating = red_end_rating
                        changed = True
                    if red.weight_for_open != red_weight_for_open:
                        red.weight_for_open = red_weight_for_open
                        changed = True
                    if red.rating_note != red_rating_note:
                        red.rating_note = red_rating_note
                        changed = True
                    if red.start_match_count != red_start_match_count:
                        red.start_match_count = red_start_match_count
                        changed = True
                    if red.end_match_count != red_end_match_count:
                        red.end_match_count = red_end_match_count
                        changed = True
                if athlete_id is None or athlete_id == str(blue.athlete_id):
                    if blue.start_rating != blue_start_rating:
                        blue.start_rating = blue_start_rating
                        changed = True
                    if blue.end_rating != blue_end_rating:
                        blue.end_rating = blue_end_rating
                        changed = True
                    if blue.weight_for_open != blue_weight_for_open:
                        blue.weight_for_open = blue_weight_for_open
                        changed = True
                    if blue.rating_note != blue_rating_note:
                        blue.rating_note = blue_rating_note
                        changed = True
                    if blue.start_match_count != blue_start_match_count:
                        blue.start_match_count = blue_start_match_count
                        changed = True
                    if blue.end_match_count != blue_end_match_count:
                        blue.end_match_count = blue_end_match_count
                        changed = True
                if match.rated != rated:
                    match.rated = rated
                    changed = True

                if changed:
                    db.session.flush()

    if not teens and rerank and (rerankgi or reranknogi):
        if rerankgi and reranknogi:
            desc = "gi/no-gi"
        elif rerankgi:
            desc = "gi"
        else:
            desc = "no-gi"
        log.info(f"Regenerating {desc} ranking board...")
        generate_current_ratings(db, rerankgi, reranknogi, rank_previous_date)
