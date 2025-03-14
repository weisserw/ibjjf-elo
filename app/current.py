import os
from datetime import datetime, timedelta
from typing import Optional, List
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from models import Suspension
from normalize import normalize
from constants import (
    OPEN_CLASS,
    OPEN_CLASS_LIGHT,
    OPEN_CLASS_HEAVY,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
)
from elo import RATING_VERY_IMMATURE_COUNT
import logging

log = logging.getLogger("ibjjf")


def get_ratings_query(gi_in: str, date_where: str, banned: List[str]) -> str:
    return f"""
        WITH
        athlete_max_belts AS (
            SELECT
                MAX(CASE WHEN d.belt = 'WHITE' THEN 1
                         WHEN d.belt = 'BLUE' THEN 2
                         WHEN d.belt = 'PURPLE' THEN 3
                         WHEN d.belt = 'BROWN' THEN 4
                         ELSE 5 END) AS belt_num, mp.athlete_id
            FROM matches m
            JOIN match_participants mp ON m.id = mp.match_id
            JOIN athletes a ON a.id = mp.athlete_id
            JOIN divisions d ON d.id = m.division_id
            WHERE {date_where}
            AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
            GROUP BY mp.athlete_id
        ), athlete_belts AS (
            SELECT CASE WHEN mb.belt_num = 1 THEN 'WHITE'
                        WHEN mb.belt_num = 2 THEN 'BLUE'
                        WHEN mb.belt_num = 3 THEN 'PURPLE'
                        WHEN mb.belt_num = 4 THEN 'BROWN'
                        ELSE 'BLACK' END AS belt, mb.athlete_id
            FROM athlete_max_belts mb
        ), athlete_adults AS (
            SELECT DISTINCT mp.athlete_id
            FROM matches m
            JOIN match_participants mp ON m.id = mp.match_id
            JOIN athletes a ON a.id = mp.athlete_id
            JOIN divisions d ON d.id = m.division_id
            WHERE {date_where}
            AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
            AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
        ), athlete_won_matches AS (
            SELECT DISTINCT
                mp.athlete_id,
                d.gi,
                d.gender,
                d.age,
                d.belt,
                d.weight
            FROM match_participants mp
            JOIN matches m ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
            JOIN athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
            WHERE mp.winner = TRUE
            AND {date_where}
            AND m.happened_at >= :activity_period
            AND d.gi in ({gi_in})
            AND m.rated
            AND (
                (mp.athlete_id IN (SELECT athlete_id FROM athlete_adults) AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2))
                OR (mp.athlete_id NOT IN (SELECT athlete_id FROM athlete_adults))
            )
        ), athlete_lost_matches AS (
            SELECT DISTINCT
                mp.athlete_id,
                d.gi,
                d.gender,
                d.age,
                d.belt,
                d.weight
            FROM match_participants mp
            JOIN matches m ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
            JOIN athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
            WHERE mp.winner = FALSE
            AND {date_where}
            AND m.happened_at >= :activity_period
            AND d.gi in ({gi_in})
            AND m.rated
            AND (
                (mp.athlete_id IN (SELECT athlete_id FROM athlete_adults) AND d.age NOT LIKE 'Juvenile%')
                OR (mp.athlete_id NOT IN (SELECT athlete_id FROM athlete_adults))
            )
        ), athlete_weights_no_p4p AS (
            SELECT DISTINCT
                mp.athlete_id,
                d.gi,
                d.gender,
                d.age,
                d.belt,
                d.weight
            FROM match_participants mp
            JOIN matches m ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
            WHERE {date_where} AND d.weight NOT IN (:OPEN_CLASS, :OPEN_CLASS_LIGHT, :OPEN_CLASS_HEAVY) AND (
                -- to qualify for a weight class, the athlete must have either won a match in this weight division...
                EXISTS (
                    SELECT 1
                    FROM athlete_won_matches wm
                    WHERE wm.athlete_id = mp.athlete_id
                    AND wm.gi = d.gi
                    AND wm.gender = d.gender
                    AND wm.age = d.age
                    AND wm.belt = d.belt
                    AND wm.weight = d.weight
                ) OR (
                    -- ...or lost a match in this division and not won a match at a different weight
                    EXISTS (
                        SELECT 1
                        FROM athlete_lost_matches lm
                        WHERE lm.athlete_id = mp.athlete_id
                        AND lm.gi = d.gi
                        AND lm.gender = d.gender
                        AND lm.age = d.age
                        AND lm.belt = d.belt
                        AND lm.weight = d.weight
                    ) AND NOT EXISTS (
                        SELECT 1
                        FROM athlete_won_matches wm
                        WHERE wm.athlete_id = mp.athlete_id
                        AND wm.gi = d.gi
                        AND wm.gender = d.gender
                        AND wm.age = d.age
                        AND wm.belt = d.belt
                        AND wm.weight != d.weight
                    )
                )
            )
        ), athlete_weights AS (
            SELECT * FROM athlete_weights_no_p4p
            UNION ALL
            SELECT athlete_id, gi, gender, age, belt, '' AS weight FROM (
                SELECT athlete_id, gi, gender, age, belt
                FROM athlete_won_matches
                UNION
                SELECT athlete_id, gi, gender, age, belt
                FROM athlete_lost_matches
            ) q
        ), recent_matches AS (
            SELECT
                m.happened_at,
                mp.athlete_id,
                mp.end_rating,
                mp.end_match_count,
                d.gi,
                d.gender,
                m.id AS match_id,
                ROW_NUMBER() OVER (PARTITION BY mp.athlete_id, d.gi, d.gender ORDER BY m.happened_at DESC, m.id) AS rn
            FROM matches m
            JOIN match_participants mp ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
            JOIN athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
            WHERE d.gi in ({gi_in}) AND {date_where}
        ), ratings AS (
            SELECT
                rm.athlete_id,
                rm.end_rating,
                rm.end_match_count,
                rm.gender,
                aw.age,
                aw.belt,
                rm.gi,
                aw.weight,
                rm.happened_at
            FROM recent_matches rm
            JOIN athlete_weights aw ON aw.athlete_id = rm.athlete_id
                AND aw.gi = rm.gi
                AND aw.gender = rm.gender
            WHERE rm.rn = 1
        )
        SELECT
            athlete_id,
            gender,
            age,
            belt,
            gi,
            weight,
            end_rating,
            end_match_count,
            happened_at,
            RANK() OVER (
                PARTITION BY gender, age, belt, gi, weight
                ORDER BY
                    CASE WHEN end_match_count <= :RATING_VERY_IMMATURE_COUNT THEN 1 ELSE 0 END ASC,
                    ROUND(end_rating) DESC
            ) AS rank
        FROM ratings
            """


def previous_tuesday(dt: datetime) -> datetime:
    # if today is tuesday, go back one day
    if dt.weekday() == 1:
        dt -= timedelta(days=1)
    # go back to the previous tuesday
    while dt.weekday() != 1:
        dt -= timedelta(days=1)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def generate_current_ratings(
    db: SQLAlchemy, gi: bool, nogi: bool, rank_previous_date: Optional[datetime]
) -> None:
    if gi and nogi:
        gi_in = "true, false"
    elif gi:
        gi_in = "true"
    elif nogi:
        gi_in = "false"

    activity_period = datetime.now() - relativedelta(years=1, months=1)

    if rank_previous_date is None:
        rank_previous_date = datetime.now()

    previous_date = previous_tuesday(rank_previous_date)
    while True:
        count = db.session.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM matches m
                JOIN divisions d ON m.division_id = d.id
                WHERE m.happened_at >= :previous_date
                AND d.gi in ({gi_in})
                """
            ),
            {"previous_date": previous_date},
        ).scalar()

        if count > 0:
            break

        previous_date = previous_tuesday(previous_date)

    log.info(f"Will show rating / ranking changes since: {previous_date}")

    db.session.execute(
        text(
            f"""
            DELETE FROM athlete_ratings where gi in ({gi_in})
            """
        )
    )

    if os.getenv("DATABASE_URL"):
        id_generate = "gen_random_uuid()"
    else:
        id_generate = "c.athlete_id || '-' || c.gender || '-' || c.age || '-' || c.gi || '-' || c.weight"

    banned = (
        db.session.query(Suspension.athlete_name)
        .filter(Suspension.end_date > datetime.now())
        .all()
    )
    banned_normalized = [normalize(b[0]) for b in banned]

    ratings_board = get_ratings_query(gi_in, "true", banned_normalized)
    previous_ratings_board = get_ratings_query(
        gi_in, "m.happened_at < :previous_date", banned_normalized
    )

    db.session.execute(
        text(
            f"""
        CREATE TEMPORARY TABLE temp_previous_ratings AS
        {previous_ratings_board}
            """
        ),
        {
            "OPEN_CLASS": OPEN_CLASS,
            "OPEN_CLASS_LIGHT": OPEN_CLASS_LIGHT,
            "OPEN_CLASS_HEAVY": OPEN_CLASS_HEAVY,
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "RATING_VERY_IMMATURE_COUNT": RATING_VERY_IMMATURE_COUNT,
            "activity_period": activity_period,
            "previous_date": previous_date,
        },
    )
    db.session.execute(text("ANALYZE temp_previous_ratings"))

    db.session.execute(
        text(
            f"""
        CREATE TEMPORARY TABLE temp_current_ratings AS
        {ratings_board}
            """
        ),
        {
            "OPEN_CLASS": OPEN_CLASS,
            "OPEN_CLASS_LIGHT": OPEN_CLASS_LIGHT,
            "OPEN_CLASS_HEAVY": OPEN_CLASS_HEAVY,
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "RATING_VERY_IMMATURE_COUNT": RATING_VERY_IMMATURE_COUNT,
            "activity_period": activity_period,
            "previous_date": previous_date,
        },
    )
    db.session.execute(text("ANALYZE temp_current_ratings"))

    db.session.execute(
        text(
            f"""
        INSERT INTO athlete_ratings (id, athlete_id, gender, age, belt, gi, weight,
                                     rating, match_count, match_happened_at, rank, previous_rating, previous_rank, previous_match_count)
        SELECT {id_generate}, c.*, p.end_rating, p.rank, p.end_match_count
        FROM temp_current_ratings c
        LEFT JOIN temp_previous_ratings p ON c.athlete_id = p.athlete_id AND c.gender = p.gender AND c.age = p.age AND
                                             c.belt = p.belt AND c.gi = p.gi AND c.weight = p.weight;
            """
        )
    )

    db.session.execute(text("DROP TABLE temp_previous_ratings"))
    db.session.execute(text("DROP TABLE temp_current_ratings"))
