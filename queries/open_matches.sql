select m.happened_at, d.gi, d.age, d.belt, d.gender, red_a.name as name1, blue_a.name as name2,
       round(red.start_rating) as start_rating1, round(red.end_rating) as end_rating1,
       round(blue.start_rating) as start_rating2, round(blue.end_rating) as end_rating2,
       d.weight as weight_division,
       red.weight_for_open as athlete_weight1, blue.weight_for_open as athlete_weight2,
       red.winner as winner1, blue.winner as winner2, m.rated_winner_only
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
where m.rated
order by m.happened_at
;
