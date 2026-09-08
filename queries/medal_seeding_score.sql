-- Compare IBJJF seeding with our provisional-aware rating order based on how
-- well each ordering predicted the eventual medalists.
--
-- Each division is scored with normalized discounted cumulative gain (NDCG):
--   gold = 3 points, silver = 2 points, bronze = 1 point, no medal = 0 points.
-- A score of 100 means the order begins gold, silver, bronze, bronze (when all
-- four medals were awarded). Athletes placed above their eventual result push
-- medal value farther down the order and reduce the score.

WITH latest_events AS (
    SELECT
        m.event_id,
        MIN(m.happened_at) AS event_date
    FROM matches AS m
    JOIN events AS e
      ON e.id = m.event_id
    WHERE e.name NOT LIKE '%Kids%'
    GROUP BY m.event_id
    ORDER BY event_date DESC, m.event_id
    LIMIT 20
),
first_event_division_appearance AS (
    -- A participant's first match in the division contains their rating and
    -- match count from before they competed in that division at this event.
    SELECT
        m.event_id,
        m.division_id,
        mp.athlete_id,
        mp.seed AS ibjjf_seed,
        mp.start_rating,
        mp.start_match_count,
        ROW_NUMBER() OVER (
            PARTITION BY m.event_id, m.division_id, mp.athlete_id
            ORDER BY m.happened_at, m.id, mp.id
        ) AS appearance_number
    FROM matches AS m
    JOIN latest_events AS le
      ON le.event_id = m.event_id
    JOIN match_participants AS mp
      ON mp.match_id = m.id
    WHERE m.rated
),
entrants AS (
    SELECT
        p.event_id,
        p.division_id,
        p.athlete_id,
        p.ibjjf_seed,
        p.start_rating,
        p.start_match_count,
        CASE md.place
            WHEN 1 THEN 3.0
            WHEN 2 THEN 2.0
            WHEN 3 THEN 1.0
            ELSE 0.0
        END AS medal_value
    FROM first_event_division_appearance AS p
    LEFT JOIN medals AS md
      ON md.event_id = p.event_id
     AND md.division_id = p.division_id
     AND md.athlete_id = p.athlete_id
     AND NOT md.default_gold
    WHERE p.appearance_number = 1
),
ranked_entrants AS (
    SELECT
        e.*,
        ROW_NUMBER() OVER (
            PARTITION BY e.event_id, e.division_id
            ORDER BY e.ibjjf_seed, e.athlete_id
        ) AS ibjjf_rank,
        ROW_NUMBER() OVER (
            PARTITION BY e.event_id, e.division_id
            ORDER BY
                CASE WHEN e.start_match_count > 4 THEN 0 ELSE 1 END,
                e.start_rating DESC,
                e.athlete_id
        ) AS our_rank
    FROM entrants AS e
),
actual_dcg AS (
    SELECT
        r.event_id,
        r.division_id,
        SUM(
            r.medal_value * LN(2.0) / LN(r.ibjjf_rank + 1.0)
        ) AS ibjjf_dcg,
        SUM(
            r.medal_value * LN(2.0) / LN(r.our_rank + 1.0)
        ) AS our_dcg,
        COUNT(*) AS entrant_count,
        COUNT(*) FILTER (WHERE r.medal_value > 0) AS medalist_count
    FROM ranked_entrants AS r
    GROUP BY r.event_id, r.division_id
),
ideal_medals AS (
    -- Rank the medals themselves by finish to get the maximum possible DCG
    -- for the medal inventory actually awarded in each division.
    SELECT
        md.event_id,
        md.division_id,
        CASE md.place
            WHEN 1 THEN 3.0
            WHEN 2 THEN 2.0
            WHEN 3 THEN 1.0
        END AS medal_value,
        ROW_NUMBER() OVER (
            PARTITION BY md.event_id, md.division_id
            ORDER BY md.place, md.athlete_id
        ) AS ideal_rank
    FROM medals AS md
    JOIN latest_events AS le
      ON le.event_id = md.event_id
    WHERE md.place IN (1, 2, 3)
      AND NOT md.default_gold
),
ideal_dcg AS (
    SELECT
        im.event_id,
        im.division_id,
        SUM(
            im.medal_value * LN(2.0) / LN(im.ideal_rank + 1.0)
        ) AS ideal_dcg
    FROM ideal_medals AS im
    GROUP BY im.event_id, im.division_id
),
division_scores AS (
    SELECT
        a.event_id,
        a.division_id,
        a.entrant_count,
        a.medalist_count,
        100.0 * a.ibjjf_dcg / NULLIF(i.ideal_dcg, 0) AS ibjjf_score,
        100.0 * a.our_dcg / NULLIF(i.ideal_dcg, 0) AS our_score
    FROM actual_dcg AS a
    JOIN ideal_dcg AS i
      ON i.event_id = a.event_id
     AND i.division_id = a.division_id
    -- Only compare divisions for which every non-default medalist appears in
    -- our rated match data. Otherwise missing medalists would silently score 0.
    WHERE a.medalist_count = (
        SELECT COUNT(*)
        FROM medals AS md
        WHERE md.event_id = a.event_id
          AND md.division_id = a.division_id
          AND md.place IN (1, 2, 3)
          AND NOT md.default_gold
    )
)
SELECT
    e.name AS event_name,
    le.event_date,
    COUNT(*) AS divisions_compared,
    SUM(ds.entrant_count) AS entrants_compared,
    ROUND(AVG(ds.ibjjf_score), 2) AS ibjjf_seeding_score,
    ROUND(AVG(ds.our_score), 2) AS our_seeding_score,
    ROUND(AVG(ds.our_score) - AVG(ds.ibjjf_score), 2) AS our_score_advantage
FROM latest_events AS le
JOIN events AS e
  ON e.id = le.event_id
JOIN division_scores AS ds
  ON ds.event_id = le.event_id
GROUP BY e.id, e.name, le.event_date
ORDER BY le.event_date DESC, e.name;
