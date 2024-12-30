import os
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from constants import OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY


def generate_current_ratings(db: SQLAlchemy) -> None:
    db.session.execute(
        text(
            """
        DELETE FROM athlete_ratings
    """
        )
    )

    if os.getenv("DATABASE_URL"):
        id_generate = "gen_random_uuid()"
    else:
        id_generate = (
            "athlete_id || '-' || gender || '-' || age || '-' || gi || '-' || weight"
        )

    db.session.execute(
        text(
            f"""
        INSERT INTO athlete_ratings (id, athlete_id, gender, age, belt, gi, weight, rating, match_happened_at, rank)
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
            JOIN divisions d ON d.id = m.division_id
            GROUP BY mp.athlete_id
        ), athlete_belts AS (
            SELECT CASE WHEN mb.belt_num = 1 THEN 'WHITE'
                        WHEN mb.belt_num = 2 THEN 'BLUE'
                        WHEN mb.belt_num = 3 THEN 'PURPLE'
                        WHEN mb.belt_num = 4 THEN 'BROWN'
                        ELSE 'BLACK' END AS belt, mb.athlete_id
            FROM athlete_max_belts mb
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
            WHERE d.weight NOT IN (:OPEN_CLASS, :OPEN_CLASS_LIGHT, :OPEN_CLASS_HEAVY) AND (
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
            )
        ), recent_matches AS (
            SELECT
                m.happened_at,
                mp.athlete_id,
                mp.end_rating,
                d.gi,
                d.gender,
                d.age,
                d.belt,
                m.id AS match_id,
                ROW_NUMBER() OVER (PARTITION BY mp.athlete_id, d.gi, d.gender, d.age ORDER BY m.happened_at DESC, m.id) AS rn
            FROM matches m
            JOIN match_participants mp ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
            JOIN athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
        ), ratings AS (
            SELECT
                rm.athlete_id,
                rm.end_rating,
                rm.gender,
                rm.age,
                rm.belt,
                rm.gi,
                aw.weight,
                rm.happened_at
            FROM recent_matches rm
            JOIN athlete_weights aw ON aw.athlete_id = rm.athlete_id
                AND aw.gi = rm.gi
                AND aw.gender = rm.gender
                AND aw.age = rm.age
                AND aw.belt = rm.belt
            WHERE rm.rn = 1
        )
        SELECT
            {id_generate},
            athlete_id,
            gender,
            age,
            belt,
            gi,
            weight,
            end_rating,
            happened_at,
            RANK() OVER (PARTITION BY gender, age, belt, gi, weight ORDER BY ROUND(end_rating) DESC) AS rank
            FROM ratings
    """
        ),
        {
            "OPEN_CLASS": OPEN_CLASS,
            "OPEN_CLASS_LIGHT": OPEN_CLASS_LIGHT,
            "OPEN_CLASS_HEAVY": OPEN_CLASS_HEAVY,
        },
    )
