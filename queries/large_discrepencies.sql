select m.id, d.gi, red_a.name as red_name, blue_a.name as blue_name, greatest(red.start_rating - blue.start_rating, blue.start_rating - red.start_rating)
from matches m
join divisions d on d.id = m.division_id
cross join lateral (
    select mp.*
    from match_participants mp
    where mp.match_id = m.id
    order by mp.start_rating
    limit 1
) red
join athletes red_a on red_a.id = red.athlete_id
cross join lateral (
    select mp.*
    from match_participants mp
    where mp.match_id = m.id
    order by mp.start_rating desc
    limit 1
) blue
join athletes blue_a on blue_a.id = blue.athlete_id
where m.rated
order by greatest(red.start_rating - blue.start_rating, blue.start_rating - red.start_rating) desc
limit 100
;