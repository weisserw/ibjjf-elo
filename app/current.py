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


def _public_age_sql(alias: str) -> str:
    return (
        f"CASE WHEN {alias}.age IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2) "
        f"THEN :JUVENILE ELSE {alias}.age END"
    )


def create_ratings_tables(
    session,
    gi_in: str,
    date_where: str,
    banned: List[str],
    activity_period: datetime,
    previous_date: Optional[datetime],
    name: str,
    match_data_source: Optional[str] = None,
) -> str:
    # Every ranking stage needs the same participant/match/division facts. Keep
    # that join and the board-date filter in one materialized temp table so the
    # growing match history is read once instead of once per stage.
    if match_data_source is None:
        session.execute(
            text(
                f"""
                CREATE TEMPORARY TABLE {name}_match_data AS
                SELECT
                    m.id AS match_id,
                    m.happened_at,
                    m.rated,
                    mp.athlete_id,
                    mp.winner,
                    mp.end_rating,
                    mp.end_match_count,
                    d.gi,
                    d.gender,
                    d.age,
                    d.belt,
                    d.weight,
                    a.normalized_name
                FROM matches m
                JOIN match_participants mp ON mp.match_id = m.id
                JOIN divisions d ON d.id = m.division_id
                JOIN athletes a ON a.id = mp.athlete_id
                WHERE {date_where}
                AND d.age IN ({rated_ages_in})
                """
            ),
            {"previous_date": previous_date},
        )
    else:
        session.execute(
            text(
                f"""
                CREATE TEMPORARY TABLE {name}_match_data AS
                SELECT *
                FROM {match_data_source} md
                WHERE {date_where.replace("m.", "md.")}
                """
            ),
            {"previous_date": previous_date},
        )
    session.execute(
        text(
            f"CREATE INDEX {name}_match_data_ix ON {name}_match_data "
            "(athlete_id, gi, gender, belt)"
        )
    )
    session.execute(text(f"ANALYZE {name}_match_data"))

    session.execute(
        text(
            f"""
                CREATE TEMPORARY TABLE {name}_athlete_belts AS
                WITH
                match_belts AS (
                    SELECT
                        MAX(CASE WHEN md.belt = 'WHITE' THEN 1
                                WHEN md.belt = 'BLUE' THEN 2
                                WHEN md.belt = 'PURPLE' THEN 3
                                WHEN md.belt = 'BROWN' THEN 4
                                ELSE 5 END) AS belt_num, md.athlete_id
                    FROM {name}_match_data md
                    WHERE md.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                    GROUP BY md.athlete_id
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
            CREATE TEMPORARY TABLE {name}_athlete_rating_belts AS
            WITH match_belts_by_style AS (
                SELECT DISTINCT
                    md.athlete_id,
                    md.gi,
                    md.gender,
                    md.belt,
                    CASE WHEN md.belt = 'WHITE' THEN 1
                         WHEN md.belt = 'BLUE' THEN 2
                         WHEN md.belt = 'PURPLE' THEN 3
                         WHEN md.belt = 'BROWN' THEN 4
                         ELSE 5 END AS belt_num
                FROM {name}_match_data md
                JOIN {name}_athlete_belts ab ON ab.athlete_id = md.athlete_id
            ),
            current_match_belts AS (
                SELECT
                    mbs.athlete_id,
                    mbs.gi,
                    mbs.gender,
                    mbs.belt
                FROM match_belts_by_style mbs
                JOIN {name}_athlete_belts ab ON ab.athlete_id = mbs.athlete_id
                    AND ab.belt = mbs.belt
            ),
            previous_promotion_belts AS (
                SELECT
                    mbs.athlete_id,
                    mbs.gi,
                    mbs.gender,
                    mbs.belt
                FROM match_belts_by_style mbs
                JOIN {name}_promotion_belts pm ON pm.athlete_id = mbs.athlete_id
                JOIN {name}_athlete_belts ab ON ab.athlete_id = mbs.athlete_id
                WHERE pm.belt_num > 1
                AND mbs.belt_num = pm.belt_num - 1
                AND pm.belt_num >= CASE WHEN ab.belt = 'WHITE' THEN 1
                                        WHEN ab.belt = 'BLUE' THEN 2
                                        WHEN ab.belt = 'PURPLE' THEN 3
                                        WHEN ab.belt = 'BROWN' THEN 4
                                        ELSE 5 END
                AND NOT EXISTS (
                    SELECT 1
                    FROM match_belts_by_style current
                    WHERE current.athlete_id = mbs.athlete_id
                    AND current.gi = mbs.gi
                    AND current.gender = mbs.gender
                    AND current.belt_num = pm.belt_num
                )
            )
            SELECT * FROM current_match_belts
            UNION
            SELECT * FROM previous_promotion_belts
            """
        ),
        {
            "previous_date": previous_date,
        },
    )
    session.execute(
        text(
            f"CREATE INDEX {name}_athlete_rating_belts_ix ON {name}_athlete_rating_belts (athlete_id, gi, gender, belt)"
        )
    )
    session.execute(text(f"ANALYZE {name}_athlete_rating_belts"))

    session.execute(
        text(
            f"""
            CREATE TEMPORARY TABLE {name}_athlete_adults AS
            WITH match_adults AS (
                SELECT DISTINCT md.athlete_id
                FROM {name}_match_data md
                WHERE md.normalized_name NOT IN ({','.join("'" + b + "'" for b in banned)})
                AND md.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
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
                md.athlete_id,
                md.gi,
                md.gender,
                {_public_age_sql("md")} AS age,
                md.belt,
                md.weight
            FROM {name}_match_data md
            JOIN {name}_athlete_rating_belts ab ON ab.athlete_id = md.athlete_id
                AND md.gi = ab.gi
                AND md.gender = ab.gender
                AND md.belt = ab.belt
            LEFT JOIN {name}_athlete_adults ta ON ta.athlete_id = md.athlete_id
            WHERE md.winner = TRUE
            AND md.happened_at >= :activity_period
            AND md.gi in ({gi_in})
            AND md.rated
            AND (
                (ta.athlete_id IS NOT NULL AND md.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2))
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
                md.athlete_id,
                md.gi,
                md.gender,
                {_public_age_sql("md")} AS age,
                md.belt,
                md.weight
            FROM {name}_match_data md
            JOIN {name}_athlete_rating_belts ab ON ab.athlete_id = md.athlete_id
                AND md.gi = ab.gi
                AND md.gender = ab.gender
                AND md.belt = ab.belt
            LEFT JOIN {name}_athlete_adults ta ON ta.athlete_id = md.athlete_id
            WHERE md.winner = FALSE
            AND md.happened_at >= :activity_period
            AND md.gi in ({gi_in})
            AND (
                (ta.athlete_id IS NOT NULL AND md.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2))
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
                    {_public_age_sql("d")} AS age,
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
                    FROM {name}_match_data md2
                    WHERE md2.athlete_id = a.id
                    AND md2.age NOT IN (:JUVENILE, :JUVENILE_1, :JUVENILE_2)
                )
            ),
            registration_promotion_weights AS (
                SELECT DISTINCT
                    a.id AS athlete_id,
                    d.gi,
                    d.gender,
                    {_public_age_sql("d")} AS age,
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
            ),
            athlete_weights_no_p4p AS (
                -- A win qualifies its exact weight division. These rows already
                -- contain the distinct contexts selected from match history.
                SELECT athlete_id, gi, gender, age, weight
                FROM {name}_athlete_won_matches
                WHERE weight NOT IN (:OPEN_CLASS, :OPEN_CLASS_LIGHT, :OPEN_CLASS_HEAVY)
                UNION
                -- A loss qualifies its division only when the athlete has not
                -- won at a different weight in the same belt/context.
                SELECT
                    lm.athlete_id,
                    lm.gi,
                    lm.gender,
                    lm.age,
                    lm.weight
                FROM {name}_athlete_lost_matches lm
                WHERE lm.weight NOT IN (:OPEN_CLASS, :OPEN_CLASS_LIGHT, :OPEN_CLASS_HEAVY)
                AND NOT EXISTS (
                    SELECT 1
                    FROM {name}_athlete_won_matches wm
                    WHERE wm.athlete_id = lm.athlete_id
                    AND wm.gi = lm.gi
                    AND wm.gender = lm.gender
                    AND wm.age = lm.age
                    AND wm.belt = lm.belt
                    AND wm.weight != lm.weight
                )
                UNION
                SELECT athlete_id, gi, gender, age, weight
                FROM registration_only_adult_weights
            ), athlete_weights AS (
                SELECT * FROM athlete_weights_no_p4p
                UNION ALL
                SELECT athlete_id, gi, gender, age, '' AS weight FROM (
                    SELECT athlete_id, gi, gender, age
                    FROM {name}_athlete_won_matches
                    UNION
                    SELECT athlete_id, gi, gender, age
                    FROM {name}_athlete_lost_matches
                    UNION
                    SELECT athlete_id, gi, gender, age
                    FROM registration_only_adult_weights
                ) q
            ), recent_matches AS (
                SELECT
                    md.happened_at,
                    md.athlete_id,
                    md.end_rating,
                    md.end_match_count,
                    md.gi,
                    md.gender,
                    md.belt,
                    md.match_id,
                    ROW_NUMBER() OVER (PARTITION BY md.athlete_id, md.gi, md.gender ORDER BY md.happened_at DESC, md.match_id) AS rn
                FROM {name}_match_data md
                JOIN {name}_athlete_rating_belts ab ON ab.athlete_id = md.athlete_id
                    AND md.gi = ab.gi
                    AND md.gender = ab.gender
                    AND md.belt = ab.belt
                WHERE md.gi in ({gi_in})
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
            rating_bases AS (
                SELECT DISTINCT
                    athlete_id,
                    end_rating,
                    end_match_count,
                    gender,
                    belt,
                    gi,
                    happened_at
                FROM ratings
            ),
            registration_promoted_ratings AS (
                SELECT
                    rb.athlete_id,
                    rb.end_rating + CASE WHEN pm.belt = 'BLACK' THEN :BLACK_PROMOTION_RATING_BUMP
                                        ELSE :COLOR_PROMOTION_RATING_BUMP END AS end_rating,
                    rb.end_match_count,
                    rpw.gender,
                    rpw.age,
                    pm.belt,
                    rpw.gi,
                    rpw.weight,
                    rb.happened_at
                FROM rating_bases rb
                JOIN {name}_promotion_belts pm ON pm.athlete_id = rb.athlete_id
                JOIN registration_promotion_weights rpw ON rpw.athlete_id = rb.athlete_id
                    AND rpw.belt = pm.belt
                    AND rpw.gi = rb.gi
                    AND rpw.gender = rb.gender
                WHERE pm.belt_num - CASE WHEN rb.belt = 'WHITE' THEN 1
                                        WHEN rb.belt = 'BLUE' THEN 2
                                        WHEN rb.belt = 'PURPLE' THEN 3
                                        WHEN rb.belt = 'BROWN' THEN 4
                                        ELSE 5 END = 1
                UNION
                SELECT
                    rb.athlete_id,
                    rb.end_rating + CASE WHEN pm.belt = 'BLACK' THEN :BLACK_PROMOTION_RATING_BUMP
                                        ELSE :COLOR_PROMOTION_RATING_BUMP END AS end_rating,
                    rb.end_match_count,
                    rpw.gender,
                    rpw.age,
                    pm.belt,
                    rpw.gi,
                    '' AS weight,
                    rb.happened_at
                FROM rating_bases rb
                JOIN {name}_promotion_belts pm ON pm.athlete_id = rb.athlete_id
                JOIN registration_promotion_weights rpw ON rpw.athlete_id = rb.athlete_id
                    AND rpw.belt = pm.belt
                    AND rpw.gi = rb.gi
                    AND rpw.gender = rb.gender
                WHERE pm.belt_num - CASE WHEN rb.belt = 'WHITE' THEN 1
                                        WHEN rb.belt = 'BLUE' THEN 2
                                        WHEN rb.belt = 'PURPLE' THEN 3
                                        WHEN rb.belt = 'BROWN' THEN 4
                                        ELSE 5 END = 1
            ),
            fallback_promoted_ratings AS (
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
            promoted_ratings AS (
                SELECT * FROM registration_promoted_ratings
                UNION
                SELECT * FROM fallback_promoted_ratings
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
                    AND pr.gi = r.gi
                    AND pr.gender = r.gender
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
    session.execute(text(f"DROP TABLE {name}_match_data"))
    session.execute(text(f"DROP TABLE {name}_athlete_belts"))
    session.execute(text(f"DROP TABLE {name}_promotion_belts"))
    session.execute(text(f"DROP TABLE {name}_athlete_rating_belts"))
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

    if db.session.get_bind().dialect.name == "postgresql":
        # Ranking generation is a single-session batch job. Its hash joins and
        # window sorts otherwise inherit the production default (currently
        # 2 MB) and spill heavily to temporary storage.
        db.session.execute(text("SET LOCAL work_mem = '32MB'"))

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
        id_generate = "lower(hex(randomblob(16)))"
        id_generate_avg = "lower(hex(randomblob(16)))"

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
        match_data_source="temp_current_ratings_match_data",
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
