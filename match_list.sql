select m.id, m.happened_at, a.name, case when winner then 'winner' else 'loser' end, mp.start_rating, mp.end_rating, d.age, d.belt, d.weight
from matches m
join match_participants mp on m.id = mp.match_id
join athletes a on a.id = mp.athlete_id
join divisions d on m.division_id = d.id
where true
and mp.athlete_id = ''
order by m.happened_at
;