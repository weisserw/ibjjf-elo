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
), recent_matches AS (
    SELECT
        mp.athlete_id,
        mp.end_rating,
        d.gi,
        d.belt,
        d.age,
        ROW_NUMBER() OVER (PARTITION BY mp.athlete_id, d.gi, d.age ORDER BY m.happened_at DESC, m.id) AS rn
    FROM matches m
    JOIN match_participants mp ON m.id = mp.match_id
    JOIN divisions d ON d.id = m.division_id
    JOIN athlete_belts ab ON ab.athlete_id = mp.athlete_id AND d.belt = ab.belt
)
SELECT a.name, rm.gi, rm.belt, rm.age, round(rm.end_rating) as rating
FROM recent_matches rm
JOIN athletes a ON a.id = rm.athlete_id
WHERE rn = 1
order by a.name, rm.gi, rm.belt, rm.age
;