WITH qualified_athletes AS (
    SELECT ar.athlete_id
    FROM athlete_ratings ar
    WHERE ar.age = 'Adult'
      AND ar.belt = 'BLACK'
      AND ar.gi IS TRUE
      AND ar.percentile IS NOT NULL
    GROUP BY ar.athlete_id
    HAVING MIN(ar.percentile) < 0.1
),
wins AS (
    SELECT
        winner.athlete_id AS winner_id,
        loser.athlete_id AS loser_id,
        m.happened_at
    FROM matches m
    JOIN divisions d
        ON d.id = m.division_id
    JOIN match_participants winner
        ON winner.match_id = m.id
       AND winner.winner IS TRUE
    JOIN match_participants loser
        ON loser.match_id = m.id
       AND loser.winner IS FALSE
    JOIN qualified_athletes qw
        ON qw.athlete_id = winner.athlete_id
    JOIN qualified_athletes ql
        ON ql.athlete_id = loser.athlete_id
    WHERE m.rated IS TRUE
      AND d.age = 'Adult'
      AND d.belt = 'BLACK'
      AND d.gi IS TRUE
      AND winner.athlete_id <> loser.athlete_id
      AND winner.team_id <> loser.team_id
),
cycles AS (
    SELECT
        ab.winner_id AS athlete_a_id,
        ab.loser_id AS athlete_b_id,
        bc.loser_id AS athlete_c_id,
        ab.happened_at AS a_beat_b_at,
        bc.happened_at AS b_beat_c_at,
        ca.happened_at AS c_beat_a_at
    FROM wins ab
    JOIN wins bc
        ON bc.winner_id = ab.loser_id
       AND bc.happened_at > ab.happened_at
    JOIN wins ca
        ON ca.winner_id = bc.loser_id
       AND ca.loser_id = ab.winner_id
       AND ca.happened_at > bc.happened_at
    WHERE ab.winner_id <> bc.loser_id

      -- B must never have beaten A.
      AND NOT EXISTS (
          SELECT 1
          FROM wins ba
          WHERE ba.winner_id = ab.loser_id
            AND ba.loser_id = ab.winner_id
      )

      -- C must never have beaten B.
      AND NOT EXISTS (
          SELECT 1
          FROM wins cb
          WHERE cb.winner_id = bc.loser_id
            AND cb.loser_id = bc.winner_id
      )

      -- A must never have beaten C.
      AND NOT EXISTS (
          SELECT 1
          FROM wins ac
          WHERE ac.winner_id = ab.winner_id
            AND ac.loser_id = bc.loser_id
      )
),
keyed_cycles AS (
    SELECT
        cy.*,
        keys.sorted_athlete_ids
    FROM cycles cy
    CROSS JOIN LATERAL (
        SELECT ARRAY_AGG(athlete_id ORDER BY athlete_id) AS sorted_athlete_ids
        FROM UNNEST(
            ARRAY[
                cy.athlete_a_id,
                cy.athlete_b_id,
                cy.athlete_c_id
            ]
        ) AS ids(athlete_id)
    ) keys
),
unique_cycles AS (
    SELECT
        kc.*,
        ROW_NUMBER() OVER (
            PARTITION BY kc.sorted_athlete_ids
            ORDER BY
                kc.a_beat_b_at,
                kc.b_beat_c_at,
                kc.c_beat_a_at,
                kc.athlete_a_id,
                kc.athlete_b_id,
                kc.athlete_c_id
        ) AS cycle_number
    FROM keyed_cycles kc
)
SELECT
    a.personal_name AS athlete_a,
    b.personal_name AS athlete_b,
    c.personal_name AS athlete_c
FROM unique_cycles cy
JOIN athletes a ON a.id = cy.athlete_a_id
JOIN athletes b ON b.id = cy.athlete_b_id
JOIN athletes c ON c.id = cy.athlete_c_id
WHERE cy.cycle_number = 1
ORDER BY
    athlete_a,
    athlete_b,
    athlete_c;