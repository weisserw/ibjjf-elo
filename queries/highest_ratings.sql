WITH latest_matches AS (
    SELECT
        mp.athlete_id,
        a.name AS athlete_name,
        mp.end_rating,
        mp.match_id,
        m.happened_at
    FROM match_participants mp
    JOIN athletes a ON mp.athlete_id = a.id
    JOIN matches m ON mp.match_id = m.id
    JOIN divisions d ON m.division_id = d.id
    WHERE
        m.happened_at = (
            SELECT MAX(m2.happened_at)
            FROM matches m2
            JOIN match_participants mp2 ON m2.id = mp2.match_id
            WHERE mp2.athlete_id = mp.athlete_id
        )
        AND d.age = 'Adult'
        AND d.belt = 'BLACK'
        AND d.gender = 'Male'
        AND not d.gi
)
SELECT
    athlete_id,
    athlete_name,
    end_rating
FROM
    latest_matches
ORDER BY
    end_rating DESC
LIMIT 10;