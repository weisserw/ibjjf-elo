from sqlalchemy import text
import os

def generate_current_ratings(db):
    db.session.execute(text('''
        DELETE FROM athlete_ratings
    '''))

    if os.getenv('DATABASE_URL'):
        id_generate = 'gen_random_uuid()'
    else:
        id_generate = "athlete_id || '-' || gender || '-' || age || '-' || gi"

    db.session.execute(text(f'''
        INSERT INTO athlete_ratings (id, athlete_id, rating, gender, age, belt, gi, match_happened_at)
        WITH recent_matches AS (
            SELECT
                m.happened_at,
                mp.athlete_id,
                mp.end_rating,
                d.gi,
                d.gender,
                d.age,
                d.belt,
                m.id AS match_id,
                ROW_NUMBER() OVER (PARTITION BY mp.athlete_id, d.gi, d.gender, d.age ORDER BY m.happened_at DESC, m.id) AS rn
            FROM matches m
            JOIN match_participants mp ON m.id = mp.match_id
            JOIN divisions d ON d.id = m.division_id
        )
        SELECT
            {id_generate},
            athlete_id,
            end_rating,
            gender,
            age,
            belt,
            gi,
            happened_at
        FROM recent_matches
        WHERE rn = 1
    '''))
