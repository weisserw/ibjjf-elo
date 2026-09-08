-- Find one historical bracket for each requested competitor count (N).
--
-- Important: matches.division_size is the full bracket's match capacity
-- (3, 7, 15, 31, 63, 127), not its competitor count. The competitor count is
-- the highest participant seed in an event/division bracket.

WITH target_sizes(competitor_count) AS (
    VALUES
        (22), (23), (27), (29), (30), (37), (38), (39), (41),
        (43), (45), (46), (47), (53), (54), (58), (69), (70)
),
target_events(event_name) AS (
    VALUES
        ('World Master IBJJF Jiu-Jitsu Championship 2026'),
        ('Jiu-Jitsu CON International 2026'),
        ('Jiu-Jitsu CON No-Gi International 2026')
),
participant_rows AS (
    SELECT
        m.event_id,
        m.division_id,
        m.division_size AS bracket_match_count,
        m.id AS match_id,
        m.match_number,
        m.happened_at,
        mp.id AS participant_id,
        mp.athlete_id,
        mp.team_id,
        mp.seed
    FROM matches AS m
    JOIN events AS e ON e.id = m.event_id
    JOIN target_events AS te ON te.event_name = e.name
    JOIN divisions AS d ON d.id = m.division_id
    JOIN match_participants AS mp ON mp.match_id = m.id
    WHERE d.weight NOT LIKE 'Open%'
      AND m.match_number BETWEEN 1 AND m.division_size
      AND mp.seed > 0
),
team_counts AS (
    SELECT
        event_id,
        division_id,
        bracket_match_count,
        team_id,
        count(DISTINCT athlete_id) AS athlete_count
    FROM participant_rows
    GROUP BY event_id, division_id, bracket_match_count, team_id
),
team_stats AS (
    SELECT
        event_id,
        division_id,
        bracket_match_count,
        count(*) FILTER (WHERE athlete_count > 1) AS repeated_team_count,
        coalesce(sum(athlete_count - 1) FILTER (WHERE athlete_count > 1), 0)
            AS repeated_team_athlete_count
    FROM team_counts
    GROUP BY event_id, division_id, bracket_match_count
),
bracket_candidates AS (
    SELECT
        pr.event_id,
        pr.division_id,
        pr.bracket_match_count,
        max(pr.seed) AS competitor_count,
        count(DISTINCT pr.seed) AS observed_seed_count,
        count(DISTINCT pr.athlete_id) AS observed_athlete_count,
        count(DISTINCT pr.team_id) AS distinct_team_count,
        ts.repeated_team_count,
        ts.repeated_team_athlete_count,
        min(pr.happened_at) AS happened_at
    FROM participant_rows AS pr
    JOIN team_stats AS ts
      ON ts.event_id = pr.event_id
     AND ts.division_id = pr.division_id
     AND ts.bracket_match_count = pr.bracket_match_count
    GROUP BY pr.event_id, pr.division_id, pr.bracket_match_count,
             ts.repeated_team_count, ts.repeated_team_athlete_count
),
chosen AS (
    SELECT bc.*, row_number() OVER (
        PARTITION BY bc.competitor_count
        ORDER BY
            bc.repeated_team_count ASC,
            bc.repeated_team_athlete_count ASC,
            bc.observed_seed_count DESC,
            bc.observed_athlete_count DESC,
            bc.happened_at DESC,
            bc.event_id,
            bc.division_id
    ) AS example_rank
    FROM bracket_candidates AS bc
    JOIN target_sizes AS ts
      ON ts.competitor_count = bc.competitor_count
    -- Seeds should cover 1..N. Repeated teams remain eligible because the
    -- published BJJCompsystem page supplies the authoritative swap list.
    WHERE bc.observed_seed_count = bc.competitor_count
),
first_entries AS (
    SELECT
        pr.*,
        c.competitor_count,
        c.observed_seed_count,
        c.observed_athlete_count,
        c.distinct_team_count,
        c.repeated_team_count,
        c.repeated_team_athlete_count,
        row_number() OVER (
            PARTITION BY pr.event_id, pr.division_id, pr.athlete_id
            ORDER BY pr.match_number, pr.match_id, pr.participant_id
        ) AS athlete_match_rank
    FROM chosen AS c
    JOIN participant_rows AS pr
      ON pr.event_id = c.event_id
     AND pr.division_id = c.division_id
     AND pr.bracket_match_count = c.bracket_match_count
    WHERE c.example_rank = 1
),
entry_details AS (
    SELECT
        fe.*,
        opponent.seed AS first_opponent_seed,
        opponent.athlete_id AS first_opponent_athlete_id,
        opponent.team_id AS first_opponent_team_id
    FROM first_entries AS fe
    JOIN match_participants AS opponent
      ON opponent.match_id = fe.match_id
     AND opponent.id <> fe.participant_id
    WHERE fe.athlete_match_rank = 1
)
SELECT
    fe.competitor_count,
    fe.bracket_match_count,
    e.name AS event_name,
    concat_ws(' / ', d.age, d.gender, d.belt, d.weight) AS division_name,
    ''::text AS bracket_url,
    -- Human-editable format: `14-21, 10-18`, or `none`.
    ''::text AS official_swaps,
    ''::text AS verification_notes,
    fe.observed_seed_count,
    fe.observed_athlete_count,
    fe.distinct_team_count,
    fe.repeated_team_count,
    fe.repeated_team_athlete_count,
    e.ibjjf_id AS event_ibjjf_id,
    fe.event_id,
    fe.division_id,
    jsonb_agg(
        jsonb_build_object(
            'seed', fe.seed,
            'athlete_id', fe.athlete_id,
            'team_id', fe.team_id,
            'first_match_number', fe.match_number,
            'first_opponent_seed', fe.first_opponent_seed,
            'first_opponent_athlete_id', fe.first_opponent_athlete_id,
            'first_opponent_team_id', fe.first_opponent_team_id
        )
        ORDER BY fe.seed
    ) AS seed_entries
FROM entry_details AS fe
JOIN events AS e ON e.id = fe.event_id
JOIN divisions AS d ON d.id = fe.division_id
GROUP BY
    fe.competitor_count,
    fe.bracket_match_count,
    fe.observed_seed_count,
    fe.observed_athlete_count,
    fe.distinct_team_count,
    fe.repeated_team_count,
    fe.repeated_team_athlete_count,
    e.name,
    e.ibjjf_id,
    fe.event_id,
    fe.division_id,
    d.age,
    d.gender,
    d.belt,
    d.weight
ORDER BY fe.competitor_count;
