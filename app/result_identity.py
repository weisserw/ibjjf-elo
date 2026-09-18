"""Conservative identity lookup for names shown on IBJJF result pages.

An initial and surname is an identity hint, never a unique identifier.  The
resolver only assigns an athlete after all known contradictions are removed.
"""

import re
from fnmatch import fnmatchcase
from dataclasses import dataclass

from constants import belt_order
from models import (
    Athlete, AthleteRating, Division, ManualPromotions, Match, MatchParticipant,
    Medal, Team, TeamNameMapping,
)
from normalize import normalize


INITIAL_NAME = re.compile(r"^\s*([^\W\d_])\s*\.\s*(\S.*)$", re.UNICODE)
YOUTH = {"Juvenile", "Juvenile 1", "Juvenile 2"}


def initial_surname_key(name):
    """Fold accents/punctuation and index initial plus final surname token.

    The resolver checks the complete abbreviated surname against the candidate
    name after this broad index lookup. That lets ``John Michael da Silva``
    match ``J. da Silva`` while distinguishing ``da Silva`` from ``dos Silva``.
    A suffix such as ``Jr`` remains the final indexed token. A single-token
    or blank name has no usable key.
    """
    words = normalize(name or "").split()
    if len(words) < 2 or not words[0] or not words[-1]:
        return None
    return f"{words[0][0]} {words[-1]}"


def abbreviated_name_key(name):
    match = INITIAL_NAME.match(name or "")
    if not match:
        return None
    words = normalize(match.group(2)).split()
    if not words:
        return None
    return f"{normalize(match.group(1))} {words[-1]}"


def _abbreviated_surname(name):
    match = INITIAL_NAME.match(name or "")
    return normalize(match.group(2)) if match else None


@dataclass(frozen=True)
class IdentityResolution:
    status: str
    athlete: object = None
    candidates: tuple = ()
    evidence: tuple = ()


def _history(session, athlete_id, when):
    """Return known gender, ranks, ages and dated team evidence.

    Only earlier history can contradict a later youth or lower-belt entry.
    Later promotions are allowed after the source event.
    """
    genders, ages, ranks, teams = set(), set(), set(), []
    match_rows = (
        session.query(Match.happened_at, Division.gender, Division.age,
                      Division.belt, Team.name)
        .select_from(MatchParticipant)
        .join(Match, MatchParticipant.match_id == Match.id)
        .join(Division, Match.division_id == Division.id)
        .join(Team, MatchParticipant.team_id == Team.id)
        .filter(MatchParticipant.athlete_id == athlete_id)
        .all()
    )
    medal_rows = (
        session.query(Medal.happened_at, Division.gender, Division.age,
                      Division.belt, Team.name)
        .join(Division, Medal.division_id == Division.id)
        .join(Team, Medal.team_id == Team.id)
        .filter(Medal.athlete_id == athlete_id)
        .all()
    )
    for happened_at, gender, age, belt, team in (*match_rows, *medal_rows):
        if gender:
            genders.add(gender)
        if when is not None and happened_at <= when:
            if age:
                ages.add(age)
            if belt in belt_order:
                ranks.add(belt_order.index(belt))
        if team and happened_at:
            teams.append((happened_at, normalize(team)))
    for belt, promoted_at in (
        session.query(ManualPromotions.belt, ManualPromotions.promoted_at)
        .filter(ManualPromotions.athlete_id == athlete_id).all()
    ):
        if when is not None and promoted_at <= when and belt in belt_order:
            ranks.add(belt_order.index(belt))
    # Ratings can contain recorded rank evidence even when there is no match.
    for belt, gender, age, happened_at in (
        session.query(AthleteRating.belt, AthleteRating.gender,
                      AthleteRating.age, AthleteRating.match_happened_at)
        .filter(AthleteRating.athlete_id == athlete_id).all()
    ):
        if gender:
            genders.add(gender)
        if when is not None and happened_at <= when:
            ages.add(age)
            if belt in belt_order:
                ranks.add(belt_order.index(belt))
    return genders, ages, ranks, teams


def _bulk_histories(session, candidates, when):
    """Read crowded surname histories in four queries, not one set per athlete."""
    ids = [athlete.id for athlete in candidates]
    result = {athlete_id: (set(), set(), set(), []) for athlete_id in ids}

    def record(athlete_id, happened_at, gender, age, belt, team=None):
        genders, ages, ranks, teams = result[athlete_id]
        if gender:
            genders.add(gender)
        if when is not None and happened_at <= when:
            if age:
                ages.add(age)
            if belt in belt_order:
                ranks.add(belt_order.index(belt))
        if team and happened_at:
            teams.append((happened_at, normalize(team)))

    matches = (
        session.query(MatchParticipant.athlete_id, Match.happened_at,
                      Division.gender, Division.age, Division.belt, Team.name)
        .select_from(MatchParticipant)
        .join(Match, MatchParticipant.match_id == Match.id)
        .join(Division, Match.division_id == Division.id)
        .join(Team, MatchParticipant.team_id == Team.id)
        .filter(MatchParticipant.athlete_id.in_(ids)).all()
    )
    medals = (
        session.query(Medal.athlete_id, Medal.happened_at, Division.gender,
                      Division.age, Division.belt, Team.name)
        .join(Division, Medal.division_id == Division.id)
        .join(Team, Medal.team_id == Team.id)
        .filter(Medal.athlete_id.in_(ids)).all()
    )
    for athlete_id, happened_at, gender, age, belt, team in (*matches, *medals):
        record(athlete_id, happened_at, gender, age, belt, team)
    promotions = (
        session.query(ManualPromotions.athlete_id, ManualPromotions.belt,
                      ManualPromotions.promoted_at)
        .filter(ManualPromotions.athlete_id.in_(ids)).all()
    )
    for athlete_id, belt, promoted_at in promotions:
        if when is not None and promoted_at <= when and belt in belt_order:
            result[athlete_id][2].add(belt_order.index(belt))
    ratings = (
        session.query(AthleteRating.athlete_id, AthleteRating.belt,
                      AthleteRating.gender, AthleteRating.age,
                      AthleteRating.match_happened_at)
        .filter(AthleteRating.athlete_id.in_(ids)).all()
    )
    for athlete_id, belt, gender, age, happened_at in ratings:
        record(athlete_id, happened_at, gender, age, belt)
    return result


def resolve_identity(session, name, *, ibjjf_id=None, gender=None, belt=None,
                     age=None, team=None, when=None):
    """Resolve an IBJJF name to exactly one athlete, or explain why it cannot.

    Full names use the existing normalized-name index; initial names use the
    dedicated indexed key. Team evidence can break a tie only for a uniquely
    supported candidate with evidence within one year of the event.
    """
    if ibjjf_id:
        matches = session.query(Athlete).filter(Athlete.ibjjf_id == ibjjf_id).all()
        if len(matches) == 1:
            return IdentityResolution("matched", matches[0], tuple(matches), ("ibjjf_id",))
    key = abbreviated_name_key(name)
    if key:
        candidates = session.query(Athlete).filter(
            Athlete.normalized_initial_surname == key).order_by(Athlete.id).all()
        surname = _abbreviated_surname(name)
        candidates = [
            athlete for athlete in candidates
            if normalize(athlete.name).endswith(" " + surname)
        ]
    else:
        normalized = normalize(name or "")
        if not normalized:
            return IdentityResolution("unmatched", evidence=("empty_name",))
        candidates = session.query(Athlete).filter(
            Athlete.normalized_name == normalized).order_by(Athlete.id).all()
    if not candidates:
        return IdentityResolution("unmatched", evidence=("no_name_candidate",))
    viable, histories = [], {}
    bulk = _bulk_histories(session, candidates, when) if len(candidates) > 8 else None
    for athlete in candidates:
        known_genders, known_ages, known_ranks, teams = (
            bulk[athlete.id] if bulk is not None else _history(session, athlete.id, when)
        )
        histories[athlete.id] = teams
        if gender and known_genders and gender not in known_genders:
            continue
        if belt in belt_order and known_ranks and max(known_ranks) > belt_order.index(belt):
            continue
        if age in YOUTH and any(a == "Adult" or a.startswith("Master") for a in known_ages):
            continue
        viable.append(athlete)
    if len(viable) == 1:
        return IdentityResolution("matched", viable[0], tuple(viable), ("unique_compatible",))
    if len(viable) > 1 and team and when:
        mappings = session.query(TeamNameMapping.name_match, TeamNameMapping.mapped_name).all()

        def canonical_team(raw_name):
            raw_key = normalize(raw_name)
            for pattern, mapped in mappings:
                normalized_pattern = "*".join(
                    normalize(part) for part in (pattern or "").split("*")
                )
                if normalized_pattern and fnmatchcase(raw_key, normalized_pattern):
                    return normalize(mapped)
            return raw_key

        team_key = canonical_team(team)
        supported = []
        for athlete in viable:
            if any(abs((date - when).days) <= 365 and canonical_team(known_team) == team_key
                   for date, known_team in histories[athlete.id]):
                supported.append(athlete)
        if len(supported) == 1:
            return IdentityResolution("matched", supported[0], tuple(viable), ("distinctive_team",))
    return IdentityResolution("ambiguous" if viable else "unmatched",
                              candidates=tuple(viable),
                              evidence=("multiple_compatible" if viable else "contradictory_history",))
