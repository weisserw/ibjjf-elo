from sqlalchemy import text

def generate_current_ratings(db):
    db.session.execute(text('''
        DELETE FROM current_ratings
    '''))

    db.session.execute(text('''
        INSERT INTO current_ratings (athlete_id, rating, gender, age, belt, gi, match_happened_at)
        SELECT
            mp.athlete_id,
            mp.end_rating,
            d.gender,
            d.age,
            d.belt,
            d.gi,
            m.happened_at
        FROM match_participants mp
        JOIN athletes a ON mp.athlete_id = a.id
        JOIN matches m ON mp.match_id = m.id
        JOIN divisions d ON m.division_id = d.id
        WHERE
            m.happened_at = (
                SELECT MAX(m2.happened_at)
                FROM matches m2
                JOIN match_participants mp2 ON m2.id = mp2.match_id
                WHERE mp2.athlete_id = mp.athlete_id
            )
    '''))
