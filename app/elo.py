from models import Match, MatchParticipant, Division
from constants import ADULT, BLACK, BROWN, PURPLE, BLUE, WHITE, OPEN_CLASS, weight_class_order

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

# the amount of "ghost rating points" to add to the rating of an athlete in the open class,
# the index is the difference in weight classes
HANDICAPS = [
    0, 70, 240, 380, 510
]

no_match_strings = [
    'Disqualified by no show',
    'Disqualified by overweight'
]

def match_didnt_happen(note1, note2):
    for no_match_string in no_match_strings:
        if no_match_string in note1 or no_match_string in note2:
            return True
    return False


def compute_k_factor(num_matches, handicap):
    if num_matches < 5 or handicap > 0:
        return 64
    elif num_matches < 7:
        return 48
    else:
        return 32


def open_handicaps(db, match_id, happened_at, division, red_athlete_id, blue_athlete_id):
    if division.weight != OPEN_CLASS:
        return True, 0, 0

    # get the last rated non-open class match for each athlete
    red_last_non_open_division = db.session.query(Division).join(Match).join(MatchParticipant).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        ~Division.weight.startswith(OPEN_CLASS),
        Match.rated == True,
        MatchParticipant.athlete_id == red_athlete_id,
        (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc(), Match.id.desc()).first()
    blue_last_non_open_division = db.session.query(Division).join(Match).join(MatchParticipant).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        ~Division.weight.startswith(OPEN_CLASS),
        Match.rated == True,
        MatchParticipant.athlete_id == blue_athlete_id,
        (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc(), Match.id.desc()).first()

    # if one of the athletes has no non-open class matches, treat it as an equal match in adult black belt,
    # otherwise don't rate it
    if red_last_non_open_division is None or blue_last_non_open_division is None:
        if division.age == ADULT and division.belt == BLACK:
            return True, 0, 0
        else:
            return False, 0, 0

    # look up the index in the weight class order for each athlete
    red_weight_index = weight_class_order.index(red_last_non_open_division.weight)
    blue_weight_index = weight_class_order.index(blue_last_non_open_division.weight)

    weight_difference = abs(red_weight_index - blue_weight_index) 
    if weight_difference >= len(HANDICAPS):
        weight_difference = len(HANDICAPS) - 1

    red_handicap = 0
    blue_handicap = 0
    if red_weight_index < blue_weight_index:
        # if red weighs less, add points to blue's rating
        blue_handicap = HANDICAPS[weight_difference]
    else:
        red_handicap = HANDICAPS[weight_difference]

    return True, red_handicap, blue_handicap

def compute_ratings(db, match_id, division, happened_at, red_athlete_id, red_winner, red_note, blue_athlete_id, blue_winner, blue_note):
    # get the last match played by each athlete in the same division by querying the matches table
    # in reverse date order
    red_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == red_athlete_id,
        (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc(), Match.id.desc()).first()
    blue_last_match = db.session.query(MatchParticipant).join(Match).join(Division).filter(
        Division.gi == division.gi,
        Division.gender == division.gender,
        Division.age == division.age,
        MatchParticipant.athlete_id == blue_athlete_id,
        (Match.happened_at < happened_at) | ((Match.happened_at == happened_at) & (Match.id < match_id))
    ).order_by(Match.happened_at.desc(), Match.id.desc()).first()

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
    if red_winner == blue_winner:
        # there are two ways you could in theory have a draw: either both athletes are disqualified,
        # or the match wasn't finished yet when we pulled the data, so neither athlete has been marked as the loser.

        # the IBJJF doesn't seem to have a way to represent the former on their site, and we don't have a good way to show
        # draws in the UI at the moment either, so in either case we're just going to skip rating the match since its probably
        # a case of bad data
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
    if match_didnt_happen(red_note, blue_note):
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
    else:
        rated_open, red_handicap, blue_handicap = open_handicaps(db, match_id, happened_at, division, red_athlete_id, blue_athlete_id)

        if not rated_open:
            red_end_rating = red_start_rating
            blue_end_rating = blue_start_rating
            rated = False
        else:
            red_k_factor = compute_k_factor(red_match_count, red_handicap)
            blue_k_factor = compute_k_factor(blue_match_count, blue_handicap)

            k_factor = (red_k_factor + blue_k_factor) / 2

            red_elo = EloCompetitor(red_start_rating + red_handicap, k_factor)
            blue_elo = EloCompetitor(blue_start_rating + blue_handicap, k_factor)

            if red_winner:
                red_elo.beat(blue_elo)
            else:
                blue_elo.beat(red_elo)

            red_end_rating = red_elo.rating - red_handicap
            blue_end_rating = blue_elo.rating - blue_handicap

            # don't subtract points from winners
            if (red_end_rating < red_start_rating and red_winner) or (blue_end_rating < blue_start_rating and blue_winner):
                red_end_rating = red_start_rating
                blue_end_rating = blue_start_rating

            # don't let ratings go below 0, hard to image a scenario where this would happen
            # but hey...
            if red_end_rating < 0:
                red_end_rating = 0
            if blue_end_rating < 0:
                blue_end_rating = 0

    return rated, red_start_rating, red_end_rating, blue_start_rating, blue_end_rating