with multi_ages AS (
    select athlete_id, gi, count(distinct age) as age_count
    from athlete_ratings r
    group by athlete_id, gi
    having count(distinct age) > 1
),
num_matches_per_age AS (
    select p.athlete_id, d.gi, d.age, count(*) as num_matches
    from match_participants p
    join matches m on p.match_id = m.id
    join divisions d on m.division_id = d.id
    join multi_ages a on p.athlete_id = a.athlete_id and d.gi = a.gi
    group by p.athlete_id, d.gi, d.age
)
select distinct a.name, case when r.gi then 'true' else 'false' end as gi, r.belt, r.age, round(r.rating) as rating, n.num_matches
from athlete_ratings r
join athletes a on r.athlete_id = a.id
join multi_ages m on r.athlete_id = m.athlete_id and r.gi = m.gi
join num_matches_per_age n on r.athlete_id = n.athlete_id and r.gi = n.gi and r.age = n.age
order by a.name, case when r.gi then 'true' else 'false' end desc, r.age;