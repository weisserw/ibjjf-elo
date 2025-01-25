WITH
winners AS (
    SELECT mp.*, a.name
    FROM match_participants mp
    JOIN athletes a ON a.id = mp.athlete_id
    WHERE mp.winner
),
losers AS (
    SELECT mp.*, a.name
    FROM match_participants mp
    JOIN athletes a ON a.id = mp.athlete_id
    WHERE NOT mp.winner
)
SELECT d.age, d.belt,
w.name as winner_name, round(w.start_rating) as winner_start_rating, round(w.end_rating) as winner_end_rating,
case when w.rating_note like 'Promoted from%' then true else false end as winner_promoted,
l.name as loser_name, round(l.start_rating) as loser_start_rating, round(l.end_rating) as loser_end_rating,
case when l.rating_note like 'Promoted from%' then true else false end as loser_promoted
FROM matches m
JOIN divisions d ON d.id = m.division_id
JOIN winners w ON w.match_id = m.id
JOIN losers l ON l.match_id = m.id
WHERE m.rated
ORDER BY m.happened_at