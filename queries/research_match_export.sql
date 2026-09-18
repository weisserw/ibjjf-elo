-- Run from the repository root:
-- psql "$DATABASE_URL" -X -q -v ON_ERROR_STOP=1 \
--   -f queries/research_match_export.sql > research_matches.csv
-- COPY TO STDOUT writes the CSV to the client machine through shell redirection.

COPY (
    WITH ranked_participants AS (
        SELECT
            mp.*,
            row_number() OVER (
                PARTITION BY mp.match_id
                ORDER BY mp.winner DESC, mp.red DESC, mp.id
            ) AS participant_order,
            count(*) OVER (PARTITION BY mp.match_id) AS participant_count,
            count(*) FILTER (WHERE mp.winner) OVER (
                PARTITION BY mp.match_id
            ) AS recorded_winner_count
        FROM match_participants AS mp
    ),
    match_people AS (
        SELECT
            p1.match_id,
            p1.participant_count,
            p1.recorded_winner_count,
            p1.id AS winner_participant_id,
            p1.athlete_id AS winner_athlete_id,
            p1.team_id AS winner_team_id,
            p1.seed AS winner_seed,
            p1.red AS winner_red,
            p1.note AS winner_note,
            p1.rating_note AS winner_rating_note,
            p1.start_rating AS winner_start_elo,
            p1.end_rating AS winner_end_elo,
            p1.weight_for_open AS winner_open_class_weight,
            p1.start_match_count AS winner_start_match_count,
            p1.end_match_count AS winner_end_match_count,
            p1.scoreboard_position AS winner_scoreboard_position,
            p2.id AS loser_participant_id,
            p2.athlete_id AS loser_athlete_id,
            p2.team_id AS loser_team_id,
            p2.seed AS loser_seed,
            p2.red AS loser_red,
            p2.note AS loser_note,
            p2.rating_note AS loser_rating_note,
            p2.start_rating AS loser_start_elo,
            p2.end_rating AS loser_end_elo,
            p2.weight_for_open AS loser_open_class_weight,
            p2.start_match_count AS loser_start_match_count,
            p2.end_match_count AS loser_end_match_count,
            p2.scoreboard_position AS loser_scoreboard_position
        FROM ranked_participants AS p1
        LEFT JOIN ranked_participants AS p2
            ON p2.match_id = p1.match_id
           AND p2.participant_order = 2
        WHERE p1.participant_order = 1
    ),
    match_rounds AS (
        SELECT
            m.id AS match_id,
            CASE
                WHEN m.division_size > 0
                 AND m.match_number BETWEEN 1 AND m.division_size
                THEN floor(log(
                    2::numeric,
                    (m.division_size - m.match_number + 1)::numeric
                ))::integer
            END AS rounds_after_current,
            CASE
                WHEN m.division_size > 0
                 AND m.match_number BETWEEN 1 AND m.division_size
                THEN ceil(log(
                    2::numeric,
                    (m.division_size + 1)::numeric
                ))::integer
            END AS total_rounds
        FROM matches AS m
    )
    SELECT
        m.id AS match_id,
        m.happened_at AS match_datetime,
        m.happened_at::date AS match_date,
        e.id AS event_id,
        e.ibjjf_id AS event_ibjjf_id,
        e.name AS event_name,
        e.slug AS event_slug,
        d.id AS division_id,
        d.gi,
        d.gender,
        d.age AS age_class,
        d.belt,
        d.weight AS weight_division,
        m.match_number,
        m.fight_number,
        m.match_location,
        m.division_size,
        mr.total_rounds - mr.rounds_after_current AS round_number,
        mr.rounds_after_current + 1 AS rounds_remaining_including_current,
        CASE mr.rounds_after_current
            WHEN 0 THEN 'Final'
            WHEN 1 THEN 'Semifinal'
            WHEN 2 THEN 'Quarterfinal'
            WHEN 3 THEN 'Round of 16'
            WHEN 4 THEN 'Round of 32'
            WHEN 5 THEN 'Round of 64'
            WHEN 6 THEN 'Round of 128'
            ELSE CASE
                WHEN mr.rounds_after_current IS NOT NULL THEN 'Earlier round'
            END
        END AS round_name,
        mp.participant_count,
        mp.recorded_winner_count,
        wa.id AS winner_athlete_id,
        wa.ibjjf_id AS winner_athlete_ibjjf_id,
        wa.name AS winner_name,
        wa.personal_name AS winner_personal_name,
        wa.country AS winner_country,
        wt.id AS winner_team_id,
        wt.name AS winner_team,
        mp.winner_participant_id,
        mp.winner_seed,
        mp.winner_red,
        mp.winner_scoreboard_position,
        mp.winner_open_class_weight,
        mp.winner_start_elo,
        mp.winner_end_elo,
        mp.winner_end_elo - mp.winner_start_elo AS winner_elo_change,
        mp.winner_start_match_count,
        mp.winner_end_match_count,
        mp.winner_rating_note,
        mp.winner_note,
        'win'::text AS winner_outcome,
        la.id AS loser_athlete_id,
        la.ibjjf_id AS loser_athlete_ibjjf_id,
        la.name AS loser_name,
        la.personal_name AS loser_personal_name,
        la.country AS loser_country,
        lt.id AS loser_team_id,
        lt.name AS loser_team,
        mp.loser_participant_id,
        mp.loser_seed,
        mp.loser_red,
        mp.loser_scoreboard_position,
        mp.loser_open_class_weight,
        mp.loser_start_elo,
        mp.loser_end_elo,
        mp.loser_end_elo - mp.loser_start_elo AS loser_elo_change,
        mp.loser_start_match_count,
        mp.loser_end_match_count,
        mp.loser_rating_note,
        mp.loser_note,
        'loss'::text AS loser_outcome,
        CASE mp.winner_scoreboard_position
            WHEN 'top' THEN m.final_top_points
            WHEN 'bottom' THEN m.final_bottom_points
        END AS winner_points,
        CASE mp.winner_scoreboard_position
            WHEN 'top' THEN m.final_top_advantages
            WHEN 'bottom' THEN m.final_bottom_advantages
        END AS winner_advantages,
        CASE mp.winner_scoreboard_position
            WHEN 'top' THEN m.final_top_penalties
            WHEN 'bottom' THEN m.final_bottom_penalties
        END AS winner_penalties,
        CASE mp.loser_scoreboard_position
            WHEN 'top' THEN m.final_top_points
            WHEN 'bottom' THEN m.final_bottom_points
        END AS loser_points,
        CASE mp.loser_scoreboard_position
            WHEN 'top' THEN m.final_top_advantages
            WHEN 'bottom' THEN m.final_bottom_advantages
        END AS loser_advantages,
        CASE mp.loser_scoreboard_position
            WHEN 'top' THEN m.final_top_penalties
            WHEN 'bottom' THEN m.final_bottom_penalties
        END AS loser_penalties,
        m.final_top_points,
        m.final_top_advantages,
        m.final_top_penalties,
        m.final_bottom_points,
        m.final_bottom_advantages,
        m.final_bottom_penalties,
        m.final_match_time_seconds,
        CASE
            WHEN coalesce(mp.winner_note, '') ILIKE '%DQ%'
              OR coalesce(mp.loser_note, '') ILIKE '%DQ%'
                THEN 'disqualification'
            WHEN m.final_match_time_seconds > 0 THEN 'submission'
            WHEN m.final_match_time_seconds = 0
             AND m.final_top_points = m.final_bottom_points
             AND m.final_top_advantages = m.final_bottom_advantages
             AND m.final_top_penalties = m.final_bottom_penalties
                THEN 'referee_decision'
            WHEN m.final_match_time_seconds = 0
             AND (m.final_top_points IS NOT NULL
                  OR m.final_bottom_points IS NOT NULL)
                THEN 'score'
            ELSE 'unknown'
        END AS result_method_derived,
        m.rated,
        m.rated_winner_only,
        m.has_retraction,
        m.video_link AS source_video_url,
        m.video_start_offset_seconds
    FROM matches AS m
    JOIN events AS e ON e.id = m.event_id
    JOIN divisions AS d ON d.id = m.division_id
    JOIN match_people AS mp ON mp.match_id = m.id
    JOIN match_rounds AS mr ON mr.match_id = m.id
    LEFT JOIN athletes AS wa ON wa.id = mp.winner_athlete_id
    LEFT JOIN teams AS wt ON wt.id = mp.winner_team_id
    LEFT JOIN athletes AS la ON la.id = mp.loser_athlete_id
    LEFT JOIN teams AS lt ON lt.id = mp.loser_team_id
    ORDER BY
        m.happened_at,
        e.name,
        d.gender,
        d.age,
        d.belt,
        d.weight,
        m.match_number,
        m.id
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8');
