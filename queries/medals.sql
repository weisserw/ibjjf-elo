select 
m.id as medal_id,
m.happened_at::date as medal_date,
e.id as event_id,
e.ibjjf_id as event_ibjjf_id,
e.name as event_name,
e.slug as event_slug,
d.id as division_id,
d.gi,
d.gender,
d.age as age_class,
d.belt,
d.weight as weight_division,
a.id as athlete_id,
a.ibjjf_id as athlete_ibjjf_id,
a.name as athlete_name,
t.id as team_id,
t.name as team,
a.personal_name as athlete_personal_name,
a.country as athlete_country,
m.place as medal_place,
m.default_gold as medal_default_gold
from 
medals m
join events e on e.id = m.event_id
join divisions d on d.id = m.division_id
join athletes a on a.id = m.athlete_id
join teams t on t.id = m.team_id