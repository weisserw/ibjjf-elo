select red_a.name as name1, blue_a.name as name2,
       red.start_rating as rating1, blue.start_rating as rating2,
       red.weight_for_open as weight1, blue.weight_for_open as weight2,
       red.winner as winner1, blue.winner as winner2
from matches m
join divisions d on d.id = m.division_id
cross join lateral (
    select mp.*
    from match_participants mp
    where mp.match_id = m.id
    order by mp.id
    limit 1
) red
join athletes red_a on red_a.id = red.athlete_id
cross join lateral (
    select mp.*
    from match_participants mp
    where mp.match_id = m.id
    order by mp.id desc
    limit 1
) blue
join athletes blue_a on blue_a.id = blue.athlete_id
where d.weight like 'Open%' and red.weight_for_open is not null and blue.weight_for_open is not null
order by m.happened_at
;
