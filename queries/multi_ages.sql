with multi_ages AS (
    select athlete_id, gi, count(distinct age) as age_count
    from athlete_ratings r
    group by athlete_id, gi
    having count(distinct age) > 1
)
select distinct a.name, case when r.gi then 'true' else 'false' end as gi, r.belt, r.age, round(r.rating) as rating
from athlete_ratings r
join athletes a on r.athlete_id = a.id
join multi_ages m on r.athlete_id = m.athlete_id and r.gi = m.gi
order by a.name, case when r.gi then 'true' else 'false' end desc, r.age;