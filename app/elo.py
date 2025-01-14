import logging
from typing import Tuple, Optional
from datetime import datetime
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from flask_sqlalchemy import SQLAlchemy
from models import Match, MatchParticipant, Division, DefaultGold
from constants import (
    BLACK,
    BROWN,
    PURPLE,
    BLUE,
    WHITE,
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
    weight_class_order,
    belt_order,
    age_order,
)

log = logging.getLogger("ibjjf")

# EloCompetitor class based on Elote


class EloCompetitor:
    _base_rating = 400
    _k_factor = 32

    def __init__(self, initial_rating: float = 400, k_factor: int = 32):
        self._rating = initial_rating
        self._k_factor = k_factor

    @property
    def transformed_rating(self) -> float:
        return 10 ** (self._rating / self._base_rating)

    @property
    def rating(self) -> float:
        return self._rating

    @rating.setter
    def rating(self, value: float) -> None:
        self._rating = value

    def expected_score(self, competitor: "EloCompetitor") -> float:
        return self.transformed_rating / (
            competitor.transformed_rating + self.transformed_rating
        )

    def beat(self, competitor: "EloCompetitor") -> None:
        win_es = self.expected_score(competitor)
        lose_es = competitor.expected_score(self)

        self._rating = self._rating + self._k_factor * (1 - win_es)

        competitor.rating = competitor.rating + self._k_factor * (0 - lose_es)

    def tied(self, competitor: "EloCompetitor") -> None:
        win_es = self.expected_score(competitor)
        lose_es = competitor.expected_score(self)

        self._rating = self._rating + self._k_factor * (0.5 - win_es)

        competitor.rating = competitor.rating + self._k_factor * (0.5 - lose_es)


BELT_DEFAULT_RATING = {BLACK: 2000, BROWN: 1700, PURPLE: 1400, BLUE: 1100, WHITE: 800}

# the amount of "ghost rating points" to add to the rating of an athlete in the open class,
# the index is the difference in weight classes
HANDICAPS = [0, 13, 76, 85, 102, 165, 217, 302, 350]

no_match_strings = [
    "Disqualified by no show",
    "Disqualified by overweight",
    "Disqualified by acima do peso",
]


def match_didnt_happen(note1: str, note2: str) -> bool:
    for no_match_string in no_match_strings:
        if no_match_string in note1 or no_match_string in note2:
            return True
    return False


def compute_k_factor(num_matches: int, unknown_open: bool) -> int:
    if unknown_open:
        return 32
    if num_matches < 5:
        return 64
    elif num_matches < 7:
        return 48
    else:
        return 32


def open_handicaps(
    db: SQLAlchemy,
    event_id: str,
    happened_at: datetime,
    division: Division,
    red_athlete_id: str,
    blue_athlete_id: str,
) -> Tuple[bool, int, int, Optional[str], Optional[str]]:
    if division.weight not in (OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY):
        log.debug("Not an open class match")
        return False, 0, 0, None, None

    # get the last rated non-open class match for each athlete
    red_last_non_open_division = (
        db.session.query(Division.weight, Match.happened_at)
        .select_from(Division)
        .join(Match)
        .join(MatchParticipant)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            Match.rated == True,
            MatchParticipant.athlete_id == red_athlete_id,
            (Match.happened_at < happened_at) | (Match.event_id == event_id),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .first()
    )
    red_last_default_gold = (
        db.session.query(Division.weight, DefaultGold.happened_at)
        .select_from(Division)
        .join(DefaultGold)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            DefaultGold.athlete_id == red_athlete_id,
            (DefaultGold.happened_at < happened_at)
            | (DefaultGold.event_id == event_id),
        )
        .order_by(DefaultGold.happened_at.desc())
        .first()
    )
    blue_last_non_open_division = (
        db.session.query(Division.weight, Match.happened_at)
        .select_from(Division)
        .join(Match)
        .join(MatchParticipant)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            Match.rated == True,
            MatchParticipant.athlete_id == blue_athlete_id,
            (Match.happened_at < happened_at) | (Match.event_id == event_id),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .first()
    )
    blue_last_default_gold = (
        db.session.query(Division.weight, DefaultGold.happened_at)
        .select_from(Division)
        .join(DefaultGold)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            DefaultGold.athlete_id == blue_athlete_id,
            (DefaultGold.happened_at < happened_at)
            | (DefaultGold.event_id == event_id),
        )
        .order_by(DefaultGold.happened_at.desc())
        .first()
    )

    red_weight: Optional[str] = None
    blue_weight: Optional[str] = None

    if red_last_default_gold is not None or red_last_non_open_division is not None:
        if red_last_default_gold is None:
            red_weight = red_last_non_open_division.weight
        elif red_last_non_open_division is None:
            red_weight = red_last_default_gold.weight
        elif red_last_default_gold.happened_at > red_last_non_open_division.happened_at:
            red_weight = red_last_default_gold.weight
        else:
            red_weight = red_last_non_open_division.weight

    if blue_last_default_gold is not None or blue_last_non_open_division is not None:
        if blue_last_default_gold is None:
            blue_weight = blue_last_non_open_division.weight
        elif blue_last_non_open_division is None:
            blue_weight = blue_last_default_gold.weight
        elif (
            blue_last_default_gold.happened_at > blue_last_non_open_division.happened_at
        ):
            blue_weight = blue_last_default_gold.weight
        else:
            blue_weight = blue_last_non_open_division.weight

    # if one of the athletes has no non-open class matches or default golds,
    # treat it as an equal match
    if red_weight is None or blue_weight is None:
        log.debug("No non-open class matches or default golds, treating as equal match")
        return True, 0, 0, red_weight, blue_weight

    log.debug(
        "Open class match, red weight: %s, blue weight: %s", red_weight, blue_weight
    )

    # look up the index in the weight class order for each athlete
    red_weight_index = weight_class_order.index(red_weight)
    blue_weight_index = weight_class_order.index(blue_weight)

    weight_difference = abs(red_weight_index - blue_weight_index)
    if weight_difference >= len(HANDICAPS):
        weight_difference = len(HANDICAPS) - 1

    log.debug("Weight difference: %s", weight_difference)

    red_handicap = 0
    blue_handicap = 0
    if red_weight_index < blue_weight_index:
        # if red weighs less, add points to blue's rating
        blue_handicap = HANDICAPS[weight_difference]
    else:
        red_handicap = HANDICAPS[weight_difference]

    log.debug("Red handicap: %s, blue handicap: %s", red_handicap, blue_handicap)

    return False, red_handicap, blue_handicap, red_weight, blue_weight


def append_rating_note(note: Optional[str], add_note: str) -> str:
    if note is None:
        return add_note
    return note + ", " + add_note


PROMOTION_RATING_BUMP = 250


def compute_ratings(
    db: SQLAlchemy,
    event_id: str,
    match_id: str,
    division: Division,
    happened_at: datetime,
    red_athlete_id: str,
    red_winner: bool,
    red_note: str,
    blue_athlete_id: str,
    blue_winner: bool,
    blue_note: str,
) -> Tuple[
    bool, Optional[str], float, float, float, float, Optional[str], Optional[str]
]:
    log.debug(
        "Computing ratings for match %s, division %s, happened at %s, red winner: %s, blue winner: %s, red note: %s, blue note: %s",
        match_id,
        division.to_json(),
        happened_at,
        red_winner,
        blue_winner,
        red_note,
        blue_note,
    )

    younger_ages = age_order[: age_order.index(division.age)]

    # get the last match played by each athlete in the same division by querying the matches table
    # in reverse date order
    red_last_match = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            Division.age == division.age,
            MatchParticipant.athlete_id == red_athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .first()
    )
    if red_last_match is None:
        # if the athlete has no previous matches at this age, look for a younger age division to fork their rating from
        red_last_match = (
            db.session.query(MatchParticipant)
            .join(Match)
            .join(Division)
            .filter(
                Division.gi == division.gi,
                Division.gender == division.gender,
                Division.age.in_(younger_ages),
                MatchParticipant.athlete_id == red_athlete_id,
                (Match.happened_at < happened_at)
                | ((Match.happened_at == happened_at) & (Match.id < match_id)),
            )
            .order_by(
                text(
                    """
                CASE WHEN age = 'Juvenile' THEN 1
                     WHEN age = 'Adult' THEN 2
                     WHEN age = 'Master 1' THEN 3
                     WHEN age = 'Master 2' THEN 4
                     WHEN age = 'Master 3' THEN 5
                     WHEN age = 'Master 4' THEN 6
                     WHEN age = 'Master 5' THEN 7
                     WHEN age = 'Master 6' THEN 8
                     WHEN age = 'Master 7' THEN 9
                END DESC
            """
                ),
                Match.happened_at.desc(),
                Match.id.desc(),
            )
            .first()
        )

    blue_last_match = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            Division.age == division.age,
            MatchParticipant.athlete_id == blue_athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .first()
    )
    if blue_last_match is None:
        blue_last_match = (
            db.session.query(MatchParticipant)
            .join(Match)
            .join(Division)
            .filter(
                Division.gi == division.gi,
                Division.gender == division.gender,
                Division.age.in_(younger_ages),
                MatchParticipant.athlete_id == blue_athlete_id,
                (Match.happened_at < happened_at)
                | ((Match.happened_at == happened_at) & (Match.id < match_id)),
            )
            .order_by(
                text(
                    """
                CASE WHEN age = 'Juvenile' THEN 1
                     WHEN age = 'Adult' THEN 2
                     WHEN age = 'Master 1' THEN 3
                     WHEN age = 'Master 2' THEN 4
                     WHEN age = 'Master 3' THEN 5
                     WHEN age = 'Master 4' THEN 6
                     WHEN age = 'Master 5' THEN 7
                     WHEN age = 'Master 6' THEN 8
                     WHEN age = 'Master 7' THEN 9
                END DESC
            """
                ),
                Match.happened_at.desc(),
                Match.id.desc(),
            )
            .first()
        )

    # get the number of rated matches played by each athlete in the same division in the last 3 years
    three_years_prior = happened_at - relativedelta(years=3)

    red_match_count = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Match.rated == True,
            Division.gi == division.gi,
            Division.gender == division.gender,
            MatchParticipant.athlete_id == red_athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
            Match.happened_at > three_years_prior,
        )
        .count()
    )
    blue_match_count = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Match.rated == True,
            Division.gi == division.gi,
            Division.gender == division.gender,
            MatchParticipant.athlete_id == blue_athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
            Match.happened_at > three_years_prior,
        )
        .count()
    )

    if red_last_match is not None:
        log.debug("Red last match: %s", red_last_match.to_json())
    if blue_last_match is not None:
        log.debug("Blue last match: %s", blue_last_match.to_json())
    log.debug("Red match count: %s", red_match_count)
    log.debug("Blue match count: %s", blue_match_count)

    red_rating_note = None
    blue_rating_note = None

    # if the athlete has no previous matches, use the default rating for their belt
    if red_last_match is None:
        red_start_rating = BELT_DEFAULT_RATING[division.belt]
    elif (
        red_last_match.match.division.belt != division.belt
        and red_last_match.end_rating < BELT_DEFAULT_RATING[division.belt]
    ):
        previous_belt_num = belt_order.index(red_last_match.match.division.belt)
        current_belt_num = belt_order.index(division.belt)

        if current_belt_num - previous_belt_num > 1:
            log.debug(
                "Athlete was promoted more than one belt and is below default rating, using default rating"
            )
            red_start_rating = BELT_DEFAULT_RATING[division.belt]
        else:
            log.debug(
                f"Athlete was promoted one belt and is below default rating, adding {PROMOTION_RATING_BUMP} to rating"
            )
            red_start_rating = red_last_match.end_rating + PROMOTION_RATING_BUMP
        red_rating_note = (
            "Promoted from "
            + red_last_match.match.division.belt
            + " to "
            + division.belt
        )
    else:
        red_start_rating = red_last_match.end_rating

    if blue_last_match is None:
        blue_start_rating = BELT_DEFAULT_RATING[division.belt]
    elif (
        blue_last_match.match.division.belt != division.belt
        and blue_last_match.end_rating < BELT_DEFAULT_RATING[division.belt]
    ):
        previous_belt_num = belt_order.index(blue_last_match.match.division.belt)
        current_belt_num = belt_order.index(division.belt)

        if current_belt_num - previous_belt_num > 1:
            log.debug(
                "Athlete was promoted more than one belt and is below default rating, using default rating"
            )
            blue_start_rating = BELT_DEFAULT_RATING[division.belt]
        else:
            log.debug(
                f"Athlete was promoted one belt and is below default rating, adding {PROMOTION_RATING_BUMP} to rating"
            )
            blue_start_rating = blue_last_match.end_rating + PROMOTION_RATING_BUMP
        blue_rating_note = (
            "Promoted from "
            + blue_last_match.match.division.belt
            + " to "
            + division.belt
        )
    else:
        blue_start_rating = blue_last_match.end_rating

    log.debug("Start ratings: red %s, blue %s", red_start_rating, blue_start_rating)

    rated = True
    red_end_rating: float
    blue_end_rating: float

    unknown_open, red_handicap, blue_handicap, red_weight, blue_weight = (
        open_handicaps(
            db, event_id, happened_at, division, red_athlete_id, blue_athlete_id
        )
    )

    # calculate the new ratings
    if red_winner and blue_winner:
        # match wasn't finished yet when we pulled the data, so neither athlete has been marked as the loser.
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
        red_rating_note = append_rating_note(
            red_rating_note, "Unrated: winner not recorded"
        )
        blue_rating_note = append_rating_note(
            blue_rating_note, "Unrated: winner not recorded"
        )
        log.debug("Match had two winners, not rating")
    elif match_didnt_happen(red_note, blue_note):
        red_end_rating = red_start_rating
        blue_end_rating = blue_start_rating
        rated = False
        red_rating_note = append_rating_note(
            red_rating_note, "Unrated: athlete did not participate"
        )
        blue_rating_note = append_rating_note(
            blue_rating_note, "Unrated: athlete did not participate"
        )
        log.debug("Match didn't happen, not rating")
    else:
        if unknown_open:
            log.debug("Open class match with unknown weights, using minimum k factor")

        red_k_factor = compute_k_factor(red_match_count, unknown_open)
        blue_k_factor = compute_k_factor(blue_match_count, unknown_open)

        log.debug("Red k factor: %s, blue k factor: %s", red_k_factor, blue_k_factor)

        red_elo = EloCompetitor(red_start_rating + red_handicap, red_k_factor)
        blue_elo = EloCompetitor(blue_start_rating + blue_handicap, blue_k_factor)

        log.debug(
            "Start ratings with handicap: red %s, blue %s",
            red_elo.rating,
            blue_elo.rating,
        )

        if not red_winner and not blue_winner:
            red_elo.tied(blue_elo)
            red_rating_note = append_rating_note(
                red_rating_note, "Neither athlete won, rating as a tie"
            )
            blue_rating_note = append_rating_note(
                blue_rating_note, "Neither athlete won, rating as a tie"
            )
        elif red_winner:
            red_elo.beat(blue_elo)
        else:
            blue_elo.beat(red_elo)

        red_end_rating = red_elo.rating - red_handicap
        blue_end_rating = blue_elo.rating - blue_handicap

        log.debug("End ratings: red %s, blue %s", red_end_rating, blue_end_rating)

        # don't subtract points from winners
        if (red_end_rating < red_start_rating and red_winner) or (
            blue_end_rating < blue_start_rating and blue_winner
        ):
            red_end_rating = red_start_rating
            blue_end_rating = blue_start_rating
            log.debug("Winner lost points, not changing ratings")

        # don't let ratings go below 0, hard to image a scenario where this would happen
        # but hey...
        if red_end_rating < 0:
            red_end_rating = 0
            log.debug("Red rating went below 0, setting to 0")
        if blue_end_rating < 0:
            blue_end_rating = 0
            log.debug("Blue rating went below 0, setting to 0")

    return (
        rated,
        red_start_rating,
        red_end_rating,
        blue_start_rating,
        blue_end_rating,
        red_weight,
        blue_weight,
        red_rating_note,
        blue_rating_note,
    )
