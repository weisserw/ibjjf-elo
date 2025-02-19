WITH athlete_event_losses AS (
    SELECT
        mp.athlete_id,
        m.event_id,
        COUNT(*) AS losses
    FROM
        match_participants mp
    JOIN
        matches m ON mp.match_id = m.id
    WHERE
        mp.winner = FALSE
    GROUP BY
        mp.athlete_id, m.event_id
)
SELECT
    a.name AS athlete_name,
    e.name AS event_name,
    ael.losses
FROM
    athlete_event_losses ael
JOIN
    athletes a ON ael.athlete_id = a.id
JOIN
    events e ON ael.event_id = e.id
ORDER BY
    ael.losses DESC
LIMIT 10;