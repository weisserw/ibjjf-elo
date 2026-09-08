WITH latest_events AS (
    SELECT
        m.event_id,
        MIN(m.happened_at) AS event_date
    FROM matches AS m
    join events AS e
      ON e.id = m.event_id
    WHERE e.id in ('fa9dd6c2-0213-4aab-b676-b76965ef575d', 
    'adb8919d-5776-4dd5-a6f7-ab0653d6fb77',
    '40431be1-f53d-4889-9924-bdeb41bb76f6',
    '2f6274fa-3094-47f8-9342-cc938b895cdd')
    GROUP BY m.event_id
),
match_comparisons AS (
    SELECT
        m.event_id,
        m.id AS match_id,

        MAX(mp.start_rating) FILTER (WHERE mp.winner)     AS winner_start_rating,
        MAX(mp.start_rating) FILTER (WHERE NOT mp.winner) AS loser_start_rating,

        MAX(mp.start_match_count) FILTER (WHERE mp.winner)     AS winner_match_count,
        MAX(mp.start_match_count) FILTER (WHERE NOT mp.winner) AS loser_match_count,

        MAX(mp.seed) FILTER (WHERE mp.winner)             AS winner_seed,
        MAX(mp.seed) FILTER (WHERE NOT mp.winner)         AS loser_seed
    FROM matches AS m
    JOIN divisions d
      ON d.id = m.division_id
    JOIN latest_events AS le
      ON le.event_id = m.event_id
    JOIN match_participants AS mp
      ON mp.match_id = m.id
    WHERE d.age = 'Adult'
    GROUP BY m.event_id, m.id
    HAVING COUNT(*) FILTER (WHERE mp.winner) = 1
       AND COUNT(*) FILTER (WHERE NOT mp.winner) = 1
       AND m.rated
)
SELECT
    e.name AS event_name,
    le.event_date,

    COUNT(*) AS matches_compared,

    COUNT(*) FILTER (
        WHERE CASE
            WHEN mc.winner_match_count > 4 AND mc.loser_match_count <= 4 THEN TRUE
            WHEN mc.winner_match_count <= 4 AND mc.loser_match_count > 4 THEN FALSE
            ELSE mc.winner_start_rating > mc.loser_start_rating
        END
    ) AS higher_rating_wins,

    COUNT(*) FILTER (
        WHERE mc.winner_seed < mc.loser_seed
    ) AS higher_seed_wins,

    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE CASE
                WHEN mc.winner_match_count > 4 AND mc.loser_match_count <= 4 THEN TRUE
                WHEN mc.winner_match_count <= 4 AND mc.loser_match_count > 4 THEN FALSE
                ELSE mc.winner_start_rating > mc.loser_start_rating
            END
        ) / NULLIF(COUNT(*), 0),
        2
    ) AS higher_rating_win_pct,

    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE mc.winner_seed < mc.loser_seed
        )
        / COUNT(*),
        2
    ) AS higher_seed_win_pct

FROM latest_events AS le
JOIN events AS e
  ON e.id = le.event_id
JOIN match_comparisons AS mc
  ON mc.event_id = le.event_id
GROUP BY e.name, le.event_date
ORDER BY le.event_date DESC, e.name;