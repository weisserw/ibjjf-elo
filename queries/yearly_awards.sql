WITH event_ids(event_id) AS (
    VALUES
        ('2f6274fa-3094-47f8-9342-cc938b895cdd'::uuid),
        ('40431be1-f53d-4889-9924-bdeb41bb76f6'::uuid),
        ('adb8919d-5776-4dd5-a6f7-ab0653d6fb77'::uuid),
        ('fa9dd6c2-0213-4aab-b676-b76965ef575d'::uuid)
),
match_pairs AS (
    SELECT
        m.id AS match_id,
        p1.team_id AS team1_id,
        p2.team_id AS team2_id,
        t1.name AS team1_name,
        t2.name AS team2_name,
        p1.winner AS team1_winner,
        p2.winner AS team2_winner,
        p1.start_rating AS team1_rating,
        p2.start_rating AS team2_rating,
        d.weight AS division_weight,
        d.belt AS division_belt,
        p1.weight_for_open AS team1_weight_for_open,
        p2.weight_for_open AS team2_weight_for_open
    FROM matches m
    JOIN event_ids ei ON ei.event_id = m.event_id
    JOIN divisions d ON d.id = m.division_id
    JOIN match_participants p1 ON p1.match_id = m.id
    JOIN match_participants p2 ON p2.match_id = m.id
    JOIN teams t1 ON t1.id = p1.team_id
    JOIN teams t2 ON t2.id = p2.team_id
    WHERE m.rated = TRUE
      AND d.belt NOT IN ('WHITE', 'GRAY', 'YELLOW-GREY', 'YELLOW', 'ORANGE', 'GREEN-ORANGE', 'GREEN')
      AND p1.id < p2.id
      AND p1.winner != p2.winner
),
match_pairs_with_indices AS (
    SELECT
        mp.*,
        CASE mp.team1_weight_for_open
            WHEN 'Rooster' THEN 0
            WHEN 'Light Feather' THEN 1
            WHEN 'Feather' THEN 2
            WHEN 'Light' THEN 3
            WHEN 'Middle' THEN 4
            WHEN 'Medium Heavy' THEN 5
            WHEN 'Heavy' THEN 6
            WHEN 'Super Heavy' THEN 7
            WHEN 'Ultra Heavy' THEN 8
        END AS team1_weight_index,
        CASE mp.team2_weight_for_open
            WHEN 'Rooster' THEN 0
            WHEN 'Light Feather' THEN 1
            WHEN 'Feather' THEN 2
            WHEN 'Light' THEN 3
            WHEN 'Middle' THEN 4
            WHEN 'Medium Heavy' THEN 5
            WHEN 'Heavy' THEN 6
            WHEN 'Super Heavy' THEN 7
            WHEN 'Ultra Heavy' THEN 8
        END AS team2_weight_index
    FROM match_pairs mp
),
match_pairs_adjusted AS (
    SELECT
        mpi.*,
        CASE
            WHEN mpi.division_belt = 'BLACK' THEN
                CASE ABS(mpi.team1_weight_index - mpi.team2_weight_index)
                    WHEN 1 THEN 54.13
                    WHEN 2 THEN 64.47
                    WHEN 3 THEN 132.21
                    WHEN 4 THEN 168.89
                    WHEN 5 THEN 176.04
                    WHEN 6 THEN 224.28
                    WHEN 7 THEN 372.91
                    ELSE 435.37
                END
            ELSE
                CASE ABS(mpi.team1_weight_index - mpi.team2_weight_index)
                    WHEN 1 THEN 23.33
                    WHEN 2 THEN 60.99
                    WHEN 3 THEN 73.56
                    WHEN 4 THEN 119.93
                    WHEN 5 THEN 181.59
                    WHEN 6 THEN 224.28
                    WHEN 7 THEN 372.91
                    ELSE 435.37
                END
        END AS open_class_handicap
    FROM match_pairs_with_indices mpi
),
team_results AS (
    SELECT
        mp.team1_id AS team_id,
        mp.team1_name AS team_name,
        CASE WHEN mp.team1_winner THEN 1 ELSE 0 END AS won,
        (
            mp.team2_rating + CASE
                WHEN mp.division_weight LIKE 'Open Class%'
                 AND mp.team1_weight_index IS NOT NULL
                 AND mp.team2_weight_index IS NOT NULL
                 AND mp.team2_winner IS FALSE
                THEN SIGN(mp.team2_weight_index - mp.team1_weight_index) * mp.open_class_handicap
                ELSE 0
            END
        ) AS opponent_rating
    FROM match_pairs_adjusted mp
    WHERE mp.team1_id IS NOT NULL

    UNION ALL

    SELECT
        mp.team2_id AS team_id,
        mp.team2_name AS team_name,
        CASE WHEN mp.team2_winner THEN 1 ELSE 0 END AS won,
        (
            mp.team1_rating + CASE
                WHEN mp.division_weight LIKE 'Open Class%'
                 AND mp.team1_weight_index IS NOT NULL
                 AND mp.team2_weight_index IS NOT NULL
                 AND mp.team1_winner IS FALSE
                THEN SIGN(mp.team1_weight_index - mp.team2_weight_index) * mp.open_class_handicap
                ELSE 0
            END
        ) AS opponent_rating
    FROM match_pairs_adjusted mp
    WHERE mp.team2_id IS NOT NULL
),
team_competing_athletes AS (
    SELECT
        m.event_id,
        mp.team_id,
        COUNT(DISTINCT mp.athlete_id) AS competing_athletes
    FROM matches m
    JOIN event_ids ei ON ei.event_id = m.event_id
    JOIN divisions d ON d.id = m.division_id
    JOIN match_participants mp ON mp.match_id = m.id
    WHERE m.rated = TRUE
      AND d.belt NOT IN ('WHITE', 'GRAY', 'YELLOW-GREY', 'YELLOW', 'ORANGE', 'GREEN-ORANGE', 'GREEN')
      AND mp.team_id IS NOT NULL
    GROUP BY m.event_id, mp.team_id
),
eligible_teams AS (
    SELECT
        team_id,
        MIN(competing_athletes) AS min_competing_athletes,
        SUM(competing_athletes) AS total_competing_athletes,
        COUNT(*) FILTER (WHERE competing_athletes >= 15) AS events_with_15_plus
    FROM team_competing_athletes
    GROUP BY team_id
    HAVING COUNT(*) FILTER (WHERE competing_athletes >= 15) >= 2
),
team_aggregates AS (
    SELECT
        tr.team_id,
        tr.team_name,
        et.min_competing_athletes,
        et.total_competing_athletes,
        SUM(tr.won) AS wins,
        COUNT(*) AS matches,
        ROUND(100.0 * SUM(tr.won) / COUNT(*), 1) AS win_ratio,
        AVG(CASE WHEN tr.won = 1 THEN tr.opponent_rating END) AS avg_defeated_rating,
        (1.0 * SUM(tr.won) / COUNT(*))
            * COALESCE(AVG(CASE WHEN tr.won = 1 THEN tr.opponent_rating END), 0) AS adjusted_ratio
    FROM team_results tr
    JOIN eligible_teams et ON et.team_id = tr.team_id
    GROUP BY
        tr.team_id,
        tr.team_name,
        et.min_competing_athletes,
        et.total_competing_athletes
)
SELECT
    ROW_NUMBER() OVER (
        ORDER BY
            adjusted_ratio DESC,
            win_ratio DESC,
            COALESCE(avg_defeated_rating, 0) DESC,
            team_name ASC
    ) AS place,
    team_id,
    team_name,
    min_competing_athletes,
    total_competing_athletes,
    wins,
    matches,
    win_ratio,
    avg_defeated_rating,
    adjusted_ratio
FROM team_aggregates
ORDER BY place