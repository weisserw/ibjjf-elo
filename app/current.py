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
    rated_ages_in,
)
from elo import (
    RATING_VERY_IMMATURE_COUNT,
    COLOR_PROMOTION_RATING_BUMP,
    BLACK_PROMOTION_RATING_BUMP,
)
import logging

log = logging.getLogger("ibjjf")


def create_ratings_tables(
    session,
    gi_in: str,
    date_where: str,
    banned: List[str],
    activity_period: datetime,
    previous_date: Optional[datetime],
    name: str,
) -> str:
    session.execute(
        text(
            f"""
                CREATE TEMPORARY TABLE {name}_athlete_belts AS
                WITH
                match_belts AS (
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
                    AND d.age IN ({rated_ages_in})
                    AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                    GROUP BY mp.athlete_id
                )
                SELECT CASE WHEN mb.belt_num = 1 THEN 'WHITE'
                            WHEN mb.belt_num = 2 THEN 'BLUE'
                            WHEN mb.belt_num = 3 THEN 'PURPLE'
                            WHEN mb.belt_num = 4 THEN 'BROWN'
                            ELSE 'BLACK' END AS belt, mb.athlete_id
                FROM match_belts mb
            """
        ),
        {
            "previous_date": previous_date,
        },
    )
    session.execute(
        text(
            f"CREATE INDEX {name}_athlete_belts_ix ON {name}_athlete_belts (athlete_id, belt)"
        )
    )
    session.execute(text(f"ANALYZE {name}_athlete_belts"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name}_promotion_belts AS
            WITH manual_belt_promotions AS (
                SELECT CASE WHEN belt = 'WHITE' THEN 1
                            WHEN belt = 'BLUE' THEN 2
                            WHEN belt = 'PURPLE' THEN 3
                            WHEN belt = 'BROWN' THEN 4
                            ELSE 5 END AS belt_num, athlete_id
                FROM manual_promotions
                WHERE {date_where.replace("m.happened_at", "promoted_at")}
            ),
            registration_belts AS (
                SELECT CASE WHEN d.belt = 'WHITE' THEN 1
                            WHEN d.belt = 'BLUE' THEN 2
                            WHEN d.belt = 'PURPLE' THEN 3
                            WHEN d.belt = 'BROWN' THEN 4
                            ELSE 5 END AS belt_num, a.id AS athlete_id
                FROM registration_link_competitors r
                JOIN divisions d ON d.id = r.division_id
                JOIN athletes a ON a.name = r.athlete_name
                WHERE d.age IN ({rated_ages_in})
                AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                AND {
                    "false" if date_where != "true" else "true"
                }
            ),
            combined_belts AS (
                SELECT * FROM manual_belt_promotions
                UNION ALL
                SELECT * FROM registration_belts
            ),
            max_belts AS (
                SELECT athlete_id, MAX(belt_num) AS belt_num
                FROM combined_belts
                GROUP BY athlete_id
            )
            SELECT CASE WHEN mb.belt_num = 1 THEN 'WHITE'
                        WHEN mb.belt_num = 2 THEN 'BLUE'
                        WHEN mb.belt_num = 3 THEN 'PURPLE'
                        WHEN mb.belt_num = 4 THEN 'BROWN'
                        ELSE 'BLACK' END AS belt, mb.belt_num, mb.athlete_id
            FROM max_belts mb
            """
        ),
        {
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "previous_date": previous_date,
        },
    )

    session.execute(
        text(
            f"CREATE INDEX {name}_promotion_belts_ix ON {name}_promotion_belts (athlete_id, belt)"
        )
    )
    session.execute(text(f"ANALYZE {name}_promotion_belts"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name}_athlete_adults AS
            WITH match_adults AS (
                SELECT DISTINCT mp.athlete_id
                FROM matches m
                JOIN match_participants mp ON m.id = mp.match_id
                JOIN athletes a ON a.id = mp.athlete_id
                JOIN divisions d ON d.id = m.division_id
                WHERE {date_where}
                AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                AND d.age IN ({rated_ages_in})
            ),
            registration_adults AS (
                SELECT DISTINCT a.id AS athlete_id
                FROM registration_link_competitors r
                JOIN divisions d ON d.id = r.division_id
                JOIN athletes a ON a.name = r.athlete_name
                WHERE d.age IN ({rated_ages_in})
                AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                AND {
                    "false" if date_where != "true" else "true"
                }
            ),
            combined_adults AS (
                SELECT * FROM match_adults
                UNION
                SELECT * FROM registration_adults
            )
            SELECT * FROM combined_adults
            """
        ),
        {
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "previous_date": previous_date,
        },
    )
    session.execute(
        text(
            f"CREATE INDEX {name}_athlete_adults_ix ON {name}_athlete_adults (athlete_id)"
        )
    )
    session.execute(text(f"ANALYZE {name}_athlete_adults"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name}_athlete_won_matches AS
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
            JOIN {name}_athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
            LEFT JOIN {name}_athlete_adults ta ON ta.athlete_id = mp.athlete_id
            WHERE mp.winner = TRUE
            AND {date_where}
            AND m.happened_at >= :activity_period
            AND d.gi in ({gi_in})
            AND d.age in ({rated_ages_in})
            AND m.rated
            AND (
                (ta.athlete_id IS NOT NULL AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2))
                OR (ta.athlete_id IS NULL)
            )
        """
        ),
        {
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "activity_period": activity_period,
            "previous_date": previous_date,
        },
    )
    session.execute(
        text(
            f"CREATE INDEX {name}_athlete_won_matches_ix ON {name}_athlete_won_matches (athlete_id, gi, gender, age, belt, weight)"
        )
    )
    session.execute(text(f"ANALYZE {name}_athlete_won_matches"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name}_athlete_lost_matches AS
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
            JOIN {name}_athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
            LEFT JOIN {name}_athlete_adults ta ON ta.athlete_id = mp.athlete_id
            WHERE mp.winner = FALSE
            AND {date_where}
            AND m.happened_at >= :activity_period
            AND d.gi in ({gi_in})
            AND d.age in ({rated_ages_in})
            AND m.rated
            AND (
                (ta.athlete_id IS NOT NULL AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2))
                OR (ta.athlete_id IS NULL)
            )
        """
        ),
        {
            "JUVENILE": JUVENILE,
            "JUVENILE_1": JUVENILE_1,
            "JUVENILE_2": JUVENILE_2,
            "activity_period": activity_period,
            "previous_date": previous_date,
        },
    )
    session.execute(
        text(
            f"CREATE INDEX {name}_athlete_lost_matches_ix ON {name}_athlete_lost_matches (athlete_id, gi, gender, age, belt, weight)"
        )
    )
    session.execute(text(f"ANALYZE {name}_athlete_lost_matches"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name} AS
            WITH
            registration_only_adult_weights AS (
                SELECT DISTINCT
                    a.id AS athlete_id,
                    d.gi,
                    d.gender,
                    d.age,
                    d.belt,
                    d.weight
                FROM registration_link_competitors r
                JOIN divisions d ON d.id = r.division_id
                JOIN athletes a ON a.name = r.athlete_name
                WHERE d.age IN ({rated_ages_in})
                AND d.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                AND d.weight NOT IN (:OPEN_CLASS, :OPEN_CLASS_LIGHT, :OPEN_CLASS_HEAVY)
                AND a.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                AND {
                    "false" if date_where != "true" else "true"
                }
                AND NOT EXISTS (
                    SELECT 1
                    FROM matches m2
                    JOIN match_participants mp2 ON mp2.match_id = m2.id
                    JOIN divisions d2 ON d2.id = m2.division_id
                    WHERE mp2.athlete_id = a.id
                    AND {
                        "true" if date_where == "true" else date_where.replace("m.", "m2.")
                    }
                    AND d2.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                    AND d2.age IN ({rated_ages_in})
                )
            ),
            athlete_weights_no_p4p AS (
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
                        FROM {name}_athlete_won_matches wm
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
                            FROM {name}_athlete_lost_matches lm
                            WHERE lm.athlete_id = mp.athlete_id
                            AND lm.gi = d.gi
                            AND lm.gender = d.gender
                            AND lm.age = d.age
                            AND lm.belt = d.belt
                            AND lm.weight = d.weight
                        ) AND NOT EXISTS (
                            SELECT 1
                            FROM {name}_athlete_won_matches wm
                            WHERE wm.athlete_id = mp.athlete_id
                            AND wm.gi = d.gi
                            AND wm.gender = d.gender
                            AND wm.age = d.age
                            AND wm.belt = d.belt
                            AND wm.weight != d.weight
                        )
                    )
                )
                UNION
                SELECT athlete_id, gi, gender, age, belt, weight
                FROM registration_only_adult_weights
            ), athlete_weights AS (
                SELECT * FROM athlete_weights_no_p4p
                UNION ALL
                SELECT athlete_id, gi, gender, age, belt, '' AS weight FROM (
                    SELECT athlete_id, gi, gender, age, belt
                    FROM {name}_athlete_won_matches
                    UNION
                    SELECT athlete_id, gi, gender, age, belt
                    FROM {name}_athlete_lost_matches
                    UNION
                    SELECT athlete_id, gi, gender, age, belt
                    FROM registration_only_adult_weights
                ) q
            ), recent_matches AS (
                SELECT
                    m.happened_at,
                    mp.athlete_id,
                    mp.end_rating,
                    mp.end_match_count,
                    d.gi,
                    d.gender,
                    d.belt,
                    m.id AS match_id,
                    ROW_NUMBER() OVER (PARTITION BY mp.athlete_id, d.gi, d.gender ORDER BY m.happened_at DESC, m.id) AS rn
                FROM matches m
                JOIN match_participants mp ON m.id = mp.match_id
                JOIN divisions d ON d.id = m.division_id
                JOIN {name}_athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
                WHERE d.gi in ({gi_in}) AND {date_where}
                AND d.age in ({rated_ages_in})
            ), ratings AS (
                SELECT
                    rm.athlete_id,
                    rm.end_rating,
                    rm.end_match_count,
                    rm.gender,
                    aw.age,
                    rm.belt,
                    rm.gi,
                    aw.weight,
                    rm.happened_at
                FROM recent_matches rm
                JOIN athlete_weights aw ON aw.athlete_id = rm.athlete_id
                    AND aw.gi = rm.gi
                    AND aw.gender = rm.gender
                WHERE rm.rn = 1
            ),
            promoted_ratings AS (
                SELECT
                    r.athlete_id,
                    r.end_rating + CASE WHEN pm.belt = 'BLACK' THEN :BLACK_PROMOTION_RATING_BUMP
                                        ELSE :COLOR_PROMOTION_RATING_BUMP END AS end_rating,
                    r.end_match_count,
                    r.gender,
                    r.age,
                    pm.belt,
                    r.gi,
                    r.weight,
                    r.happened_at
                FROM ratings r
                JOIN {name}_promotion_belts pm ON pm.athlete_id = r.athlete_id
                WHERE pm.belt_num - CASE WHEN r.belt = 'WHITE' THEN 1
                                        WHEN r.belt = 'BLUE' THEN 2
                                        WHEN r.belt = 'PURPLE' THEN 3
                                        WHEN r.belt = 'BROWN' THEN 4
                                        ELSE 5 END = 1
            ),
            combined_ratings AS (
                -- use promoted ratings where available, otherwise use regular ratings
                SELECT * FROM promoted_ratings
                UNION ALL
                SELECT * FROM ratings r
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM promoted_ratings pr
                    WHERE pr.athlete_id = r.athlete_id
                )
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
                ) AS rank,
                CASE
                    WHEN end_match_count > :RATING_VERY_IMMATURE_COUNT THEN
                        CUME_DIST() OVER (
                        PARTITION BY gender, age, belt, gi, weight
                        ORDER BY ROUND(end_rating) DESC
                        )
                    ELSE 1
                END AS percentile
            FROM combined_ratings
            WHERE weight IS NOT NULL
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
            "COLOR_PROMOTION_RATING_BUMP": COLOR_PROMOTION_RATING_BUMP,
            "BLACK_PROMOTION_RATING_BUMP": BLACK_PROMOTION_RATING_BUMP,
            "previous_date": previous_date,
        },
    )
    session.execute(text(f"ANALYZE {name}"))


def drop_ratings_tables(session, name: str) -> None:
    session.execute(text(f"DROP TABLE {name}_athlete_belts"))
    session.execute(text(f"DROP TABLE {name}_athlete_adults"))
    session.execute(text(f"DROP TABLE {name}_athlete_won_matches"))
    session.execute(text(f"DROP TABLE {name}_athlete_lost_matches"))
    session.execute(text(f"DROP TABLE {name}"))


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
                AND d.age IN ({rated_ages_in})
                AND d.gi IN ({gi_in})
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

    db.session.execute(
        text(
            f"""
            DELETE FROM athlete_rating_averages where gi in ({gi_in})
            """
        )
    )

    if os.getenv("DATABASE_URL"):
        id_generate = "gen_random_uuid()"
        id_generate_avg = "gen_random_uuid()"
    else:
        id_generate = "c.athlete_id || '-' || c.gender || '-' || c.age || '-' || c.gi || '-' || c.weight"
        id_generate_avg = (
            "gender || '-' || age || '-' || belt || '-' || gi || '-' || weight"
        )

    banned = (
        db.session.query(Suspension.athlete_name)
        .filter(Suspension.end_date > datetime.now())
        .all()
    )
    banned_normalized = [normalize(b[0]) for b in banned]

    create_ratings_tables(
        db.session,
        gi_in,
        "true",
        banned_normalized,
        activity_period,
        None,
        "temp_current_ratings",
    )
    create_ratings_tables(
        db.session,
        gi_in,
        "m.happened_at < :previous_date",
        banned_normalized,
        activity_period,
        previous_date,
        "temp_previous_ratings",
    )

    db.session.execute(
        text(
            f"""
        INSERT INTO athlete_ratings (id, athlete_id, gender, age, belt, gi, weight,
                                     rating, match_count, match_happened_at, rank, percentile, previous_rating, previous_rank, previous_match_count, previous_percentile)
        SELECT {id_generate}, c.*, p.end_rating, p.rank, p.end_match_count, p.percentile
        FROM temp_current_ratings c
        LEFT JOIN temp_previous_ratings p ON c.athlete_id = p.athlete_id AND c.gender = p.gender AND c.age = p.age AND
                                             c.belt = p.belt AND c.gi = p.gi AND c.weight = p.weight;
            """
        )
    )

    drop_ratings_tables(db.session, "temp_current_ratings")
    drop_ratings_tables(db.session, "temp_previous_ratings")

    db.session.execute(
        text(
            f"""
        INSERT INTO athlete_rating_averages (id, gender, age, belt, gi, weight, avg_rating)
        SELECT {id_generate_avg}, gender, age, belt, gi, weight, AVG(rating)
        FROM athlete_ratings
        WHERE gi IN ({gi_in})
        GROUP BY gender, age, belt, gi, weight
            """
        )
    )
