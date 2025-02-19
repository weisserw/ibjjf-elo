WITH athlete_event_ratings AS (
    SELECT
        mp.athlete_id,
        m.event_id,
        MIN(m.happened_at) AS first_match,
        MAX(m.happened_at) AS last_match
    FROM
        match_participants mp
    JOIN
        matches m ON mp.match_id = m.id
    GROUP BY
        mp.athlete_id, m.event_id
),
rating_changes AS (
    SELECT
        aer.athlete_id,
        aer.event_id,
        mp_start.start_rating,
        mp_end.end_rating,
        (mp_end.end_rating - mp_start.start_rating) AS rating_gain
    FROM
        athlete_event_ratings aer
    JOIN
        match_participants mp_start ON aer.athlete_id = mp_start.athlete_id
        JOIN matches m_start ON mp_start.match_id = m_start.id AND aer.first_match = m_start.happened_at
    JOIN
        match_participants mp_end ON aer.athlete_id = mp_end.athlete_id
        JOIN matches m_end ON mp_end.match_id = m_end.id AND aer.last_match = m_end.happened_at
)
SELECT
    a.name AS athlete_name,
    e.name AS event_name,
    rc.rating_gain
FROM
    rating_changes rc
JOIN
    athletes a ON rc.athlete_id = a.id
JOIN
    events e ON rc.event_id = e.id
ORDER BY
    rc.rating_gain DESC
LIMIT 10;