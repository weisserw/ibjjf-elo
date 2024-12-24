from models import Match, MatchParticipant, Division
from constants import BLACK, BROWN, PURPLE, BLUE, WHITE, OPEN_CLASS, weight_class_order

# EloCompetitor class based on Elote

class EloCompetitor:
    _base_rating = 400
    _k_factor = 32

    def __init__(self, initial_rating: float = 400, k_factor: float = 32):
        self._rating = initial_rating
        self._k_factor = k_factor

    @property
    def transformed_rating(self):
        return 10 ** (self._rating / self._base_rating)

    @property
    def rating(self):
        return self._rating

    @rating.setter
    def rating(self, value):
        self._rating = value

    def expected_score(self, competitor):
        return self.transformed_rating / (competitor.transformed_rating + self.transformed_rating)

    def beat(self, competitor):
        win_es = self.expected_score(competitor)
        lose_es = competitor.expected_score(self)

        self._rating = self._rating + self._k_factor * (1 - win_es)

        competitor.rating = competitor.rating + self._k_factor * (0 - lose_es)

    def tied(self, competitor):
        win_es = self.expected_score(competitor)
        lose_es = competitor.expected_score(self)

        self._rating = self._rating + self._k_factor * (0.5 - win_es)

        competitor.rating = competitor.rating + self._k_factor * (0.5 - lose_es)

BELT_DEFAULT_RATING = {
    BLACK: 2000,
    BROWN: 1700,
    PURPLE: 1400,
    BLUE: 1100,
    WHITE: 800
}

no_match_strings = [
    'Disqualified by no show',
    'Disqualified by overweight'
]

def match_didnt_happen(note1, note2):
    for no_match_string in no_match_strings:
        if no_match_string in note1 or no_match_string in note2:
            return True
    return False


def compute_k_factor(num_matches):
    if num_matches < 5:
        return 64
    elif num_matches < 7:
        return 48
    else:
        return 32


def unrated_open_match(db, division, red_athlete_id, blue_athlete_id):
    if division.weight != OPEN_CLASS:
        return False

    # get the last rated non-open class match for each athlete
    red_last_non_open_division = db.session.query(Division).join(Match).join(MatchParticipant).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        ~Division.weight.startswith(OPEN_CLASS),
        Match.rated == True,
        MatchParticipant.athlete_id == red_athlete_id
    ).order_by(Match.happened_at.desc()).first()
    blue_last_non_open_division = db.session.query(Division).join(Match).join(MatchParticipant).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        ~Division.weight.startswith(OPEN_CLASS),
        Match.rated == True,
        MatchParticipant.athlete_id == blue_athlete_id
    ).order_by(Match.happened_at.desc()).first()

    # if one of the athletes has no non-open class matches, in theory we could not rate the
    # match since we don't know their real weight class, but this messes us up for the first
    # few tournaments because championships do the open class first, so we're going to allow this
    # for now and maybe come back and change it later
    if red_last_non_open_division is None or blue_last_non_open_division is None:
        return False

    # look up the index in the weight class order for each athlete
    red_weight_index = weight_class_order.index(red_last_non_open_division.weight)
    blue_weight_index = weight_class_order.index(blue_last_non_open_division.weight)

    # if the weight classes more than 2 apart, don't rate the match
    if abs(red_weight_index - blue_weight_index) > 2:
        return True

    return False

def compute_ratings(db, match_id, division, happened_at, red_athlete_id, red_winner, red_note, blue_athlete_id, blue_winner, blue_note):
    # get the last match played by each athlete in the same division by querying the matches table
    # in reverse date order
    red_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == red_athlete_id,
         (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc()).first()
    blue_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == blue_athlete_id,
         (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc()).first()

    # get the number of rated matches played by each athlete in the same division
    red_match_count = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Match.rated == True,
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == red_athlete_id,
         (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).count()
    blue_match_count = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Match.rated == True,
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == blue_athlete_id,
         (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).count()

    # if the athlete has no previous matches, use the default rating for their belt
    if red_last_match is None:
        red_start_rating = BELT_DEFAULT_RATING[division.belt]
    else:
        red_start_rating = red_last_match.end_rating

    if blue_last_match is None:
        blue_start_rating = BELT_DEFAULT_RATING[division.belt]
    else:
        blue_start_rating = blue_last_match.end_rating

    rated = True

    # calculate the new ratings
    if match_didnt_happen(red_note, blue_note):
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
    elif unrated_open_match(db, division, red_athlete_id, blue_athlete_id):
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
    else:
        red_k_factor = compute_k_factor(red_match_count)
        blue_k_factor = compute_k_factor(blue_match_count)

        k_factor = (red_k_factor + blue_k_factor) / 2

        red_elo = EloCompetitor(red_start_rating, k_factor)
        blue_elo = EloCompetitor(blue_start_rating, k_factor)

        # double DQ, the IBJJF web site doesn't have a way to represent this but we might as well support it anyway
        if red_winner == blue_winner:
            red_elo.tied(blue_elo)
        elif red_winner:
            red_elo.beat(blue_elo)
        else:
            blue_elo.beat(red_elo)

        red_end_rating = red_elo.rating
        blue_end_rating = blue_elo.rating

        # don't subtract points from winners
        if (red_end_rating < red_start_rating and red_winner) or (blue_end_rating < blue_start_rating and blue_winner):
            red_end_rating = red_start_rating
            blue_end_rating = blue_start_rating

    return rated, red_start_rating, red_end_rating, blue_start_rating, blue_end_rating