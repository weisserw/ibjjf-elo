WITH ranked_matches AS (
    SELECT 
        mp1.athlete_id,
        a.name AS athlete_name,
        m1.id AS match1_id,
        m1.happened_at AS match1_date,
        d1.belt AS match1_belt,
        d1.gi AS match1_gi,
        m2.id AS match2_id,
        m2.happened_at AS match2_date,
        d2.belt AS match2_belt,
        d2.gi AS match2_gi,
        ROW_NUMBER() OVER (PARTITION BY mp1.athlete_id ORDER BY m1.happened_at) AS rn
    FROM 
        match_participants mp1
    JOIN 
        matches m1 ON mp1.match_id = m1.id
    JOIN 
        divisions d1 ON m1.division_id = d1.id
    JOIN 
        match_participants mp2 ON mp1.athlete_id = mp2.athlete_id
    JOIN 
        matches m2 ON mp2.match_id = m2.id
    JOIN 
        divisions d2 ON m2.division_id = d2.id
    JOIN 
        athletes a ON mp1.athlete_id = a.id
    WHERE 
        m2.happened_at > m1.happened_at
        AND d1.gi = d2.gi
        AND (
            (d1.belt = 'BLACK' AND d2.belt IN ('BROWN', 'PURPLE', 'BLUE', 'WHITE')) OR
            (d1.belt = 'BROWN' AND d2.belt IN ('PURPLE', 'BLUE', 'WHITE')) OR
            (d1.belt = 'PURPLE' AND d2.belt IN ('BLUE', 'WHITE')) OR
            (d1.belt = 'BLUE' AND d2.belt = 'WHITE')
        )
)
SELECT 
    athlete_id,
    athlete_name,
    match1_date,
    match1_belt,
    match1_gi,
    match2_date,
    match2_belt,
    match2_gi
FROM 
    ranked_matches
WHERE 
    rn = 1
ORDER BY 
    athlete_id;