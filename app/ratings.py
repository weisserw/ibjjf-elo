from models import Match, MatchParticipant, Division
from elo import compute_ratings
from current import generate_current_ratings

def recompute_all_ratings(db, gi, gender=None, age=None, start_date=None):
    query = db.session.query(Match).join(MatchParticipant).join(Division).filter(
        Division.gi == gi
    )

    if gender is not None:
        query = query.filter(Division.gender == gender)
    if age is not None:
        query = query.filter(Division.age == age)
    if start_date is not None:
        query = query.filter(Match.happened_at >= start_date)
    
    count = 0
    for match in query.order_by(Match.happened_at, Match.id).all():
        if len(match.participants) != 2:
            print(f"Match {match.id} has {len(match.participants)} participants, skipping")
            continue

        count += 1

        red, blue = match.participants
        rated, red_start_rating, red_end_rating, blue_start_rating, blue_end_rating = compute_ratings(db, match.id, match.division, match.happened_at, red.athlete_id, red.winner, red.note, blue.athlete_id, blue.winner, blue.note)

        changed = False

        if red.start_rating != red_start_rating:
            red.start_rating = red_start_rating
            changed = True
        if red.end_rating != red_end_rating:
            red.end_rating = red_end_rating
            changed = True
        if blue.start_rating != blue_start_rating:
            blue.start_rating = blue_start_rating
            changed = True
        if blue.end_rating != blue_end_rating:
            blue.end_rating = blue_end_rating
            changed = True
        if match.rated != rated:
            match.rated = rated
            changed = True

        if changed:
            db.session.flush()

    generate_current_ratings(db)

    return count
