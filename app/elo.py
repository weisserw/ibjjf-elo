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
HANDICAPS = [0, 85, 123, 164, 200, 296, 382, 491, 511]

no_match_strings = [
    "Disqualified by no show",
    "Disqualified by overweight",
    "Disqualified by acima do peso",
    "Disqualified by withdraw",
]

COLOR_PROMOTION_RATING_BUMP = 140
BLACK_PROMOTION_RATING_BUMP = 100


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


def get_weight(
    db, division: Division, athlete_id, happened_at, event_id
) -> Optional[str]:
    last_non_open_division = (
        db.session.query(Division.weight, Match.happened_at)
        .select_from(Division)
        .join(Match)
        .join(MatchParticipant)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            Match.rated == True,
            MatchParticipant.athlete_id == athlete_id,
            (Match.happened_at < happened_at) | (Match.event_id == event_id),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .limit(1)
        .first()
    )
    last_default_gold = (
        db.session.query(Division.weight, DefaultGold.happened_at)
        .select_from(Division)
        .join(DefaultGold)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            ~Division.weight.startswith(OPEN_CLASS),
            DefaultGold.athlete_id == athlete_id,
            (DefaultGold.happened_at < happened_at)
            | (DefaultGold.event_id == event_id),
        )
        .order_by(DefaultGold.happened_at.desc())
        .limit(1)
        .first()
    )

    weight: Optional[str] = None

    if last_default_gold is not None or last_non_open_division is not None:
        if last_default_gold is None:
            weight = last_non_open_division.weight
        elif last_non_open_division is None:
            weight = last_default_gold.weight
        elif last_default_gold.happened_at > last_non_open_division.happened_at:
            weight = last_default_gold.weight
        else:
            weight = last_non_open_division.weight

    return weight


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

    red_weight = get_weight(db, division, red_athlete_id, happened_at, event_id)
    blue_weight = get_weight(db, division, blue_athlete_id, happened_at, event_id)

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


def compute_start_rating(
    division: Division, last_match: MatchParticipant
) -> Tuple[float, Optional[str]]:
    rating_note = None

    if division.belt == BLACK:
        promotion_rating_bump = BLACK_PROMOTION_RATING_BUMP
    else:
        promotion_rating_bump = COLOR_PROMOTION_RATING_BUMP

    previous_belt_num = current_belt_num = belt_order.index(division.belt)
    if last_match is not None:
        previous_belt_num = belt_order.index(last_match.match.division.belt)
        if previous_belt_num > current_belt_num:
            previous_belt_num = current_belt_num
            log.debug("Invalid data: athlete promoted backward")

    # if the athlete has no previous matches, use the default rating
    if last_match is None:
        log.debug("Athlete has no previous matches, using default rating")
        start_rating = BELT_DEFAULT_RATING[division.belt]
    elif (
        current_belt_num - previous_belt_num > 1
        and last_match.end_rating < BELT_DEFAULT_RATING[division.belt]
    ) or (current_belt_num != previous_belt_num):
        if current_belt_num - previous_belt_num > 1:
            log.debug(
                "Athlete was promoted more than one belt and is below default rating, using default rating"
            )
            start_rating = BELT_DEFAULT_RATING[division.belt]
        else:
            log.debug(
                f"Athlete was promoted one belt, adding {promotion_rating_bump} to rating"
            )
            start_rating = last_match.end_rating + promotion_rating_bump
        rating_note = (
            f"Promoted from {last_match.match.division.belt} to {division.belt}"
        )
    else:
        start_rating = last_match.end_rating

    return start_rating, rating_note


def get_last_match(db, division, athlete_id, happened_at, match_id):
    younger_ages = age_order[: age_order.index(division.age)]

    last_match = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Division.gi == division.gi,
            Division.gender == division.gender,
            Division.age == division.age,
            MatchParticipant.athlete_id == athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
        )
        .order_by(Match.happened_at.desc(), Match.id.desc())
        .limit(1)
        .first()
    )
    if last_match is None:
        log.debug("Athlete has no matches at this age, looking for younger age")
        # if the athlete has no previous matches at this age, look for a younger age division to fork their rating from
        last_match = (
            db.session.query(MatchParticipant)
            .join(Match)
            .join(Division)
            .filter(
                Division.gi == division.gi,
                Division.gender == division.gender,
                Division.age.in_(younger_ages),
                MatchParticipant.athlete_id == athlete_id,
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
            .limit(1)
            .first()
        )
        if (
            last_match is not None
            and last_match.end_rating < BELT_DEFAULT_RATING[division.belt]
        ):
            log.debug(
                "Athlete has no matches at this age and younger age is below default rating (%s), using default rating",
                last_match.end_rating,
            )
            last_match = None

    return last_match


def get_match_count(db, period, division, athlete_id, happened_at, match_id):
    match_count = (
        db.session.query(MatchParticipant)
        .join(Match)
        .join(Division)
        .filter(
            Match.rated == True,
            Division.gi == division.gi,
            Division.gender == division.gender,
            MatchParticipant.athlete_id == athlete_id,
            (Match.happened_at < happened_at)
            | ((Match.happened_at == happened_at) & (Match.id < match_id)),
            Match.happened_at > period,
        )
        .count()
    )

    return match_count


def compute_ratings(
    db: SQLAlchemy,
    event_id: str,
    match_id: str,
    division: Division,
    happened_at: datetime,
    rate_winner_only: bool,
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
        "Computing ratings for match %s, division %s, happened at %s, rate_winner_only: %s, red winner: %s, blue winner: %s, red note: %s, blue note: %s",
        match_id,
        division.to_json(),
        happened_at,
        rate_winner_only,
        red_winner,
        blue_winner,
        red_note,
        blue_note,
    )

    red_last_match = get_last_match(db, division, red_athlete_id, happened_at, match_id)
    blue_last_match = get_last_match(
        db, division, blue_athlete_id, happened_at, match_id
    )

    # get the number of rated matches played by each athlete in the same division in the last 3 years
    three_years_prior = happened_at - relativedelta(years=3)

    red_match_count = get_match_count(
        db, three_years_prior, division, red_athlete_id, happened_at, match_id
    )
    blue_match_count = get_match_count(
        db, three_years_prior, division, blue_athlete_id, happened_at, match_id
    )

    if red_last_match is not None:
        log.debug("Red last match: %s", red_last_match.to_json())
    if blue_last_match is not None:
        log.debug("Blue last match: %s", blue_last_match.to_json())
    log.debug("Red match count: %s", red_match_count)
    log.debug("Blue match count: %s", blue_match_count)

    red_start_rating, red_rating_note = compute_start_rating(division, red_last_match)
    blue_start_rating, blue_rating_note = compute_start_rating(
        division, blue_last_match
    )

    log.debug("Start ratings: red %s, blue %s", red_start_rating, blue_start_rating)

    rated = True
    red_end_rating: float
    blue_end_rating: float

    unknown_open, red_handicap, blue_handicap, red_weight, blue_weight = open_handicaps(
        db, event_id, happened_at, division, red_athlete_id, blue_athlete_id
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

        if rate_winner_only:
            if red_winner and not blue_winner:
                blue_end_rating = blue_start_rating
                blue_rating_note = append_rating_note(
                    blue_rating_note,
                    "Unrated: sourced from medalists, silver keeps rating",
                )
                log.debug("Blue rating not changed, only rating the winner")
            elif blue_winner and not red_winner:
                red_end_rating = red_start_rating
                red_rating_note = append_rating_note(
                    red_rating_note,
                    "Unrated: sourced from medalists, silver keeps rating",
                )
                log.debug("Red rating not changed, only rating the winner")

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
