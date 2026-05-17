"""Shared helpers for importing medals from result_medals into the canonical medals table.

Used by both the admin routes (`/missing_medals_scan`, `/athlete_medals/find_missing`,
import endpoints) and the CLI scripts (`match_historical_medals.py`,
`import_recent_missing_medals.py`).
"""

import os
import re
import sys
from datetime import datetime
from typing import Optional

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
)

from models import (  # noqa: E402
    Division,
    Event,
    Match,
    MatchParticipant,
    Medal,
    ResultMedal,
    Team,
)
from normalize import normalize  # noqa: E402
from constants import (  # noqa: E402
    belt_order,
    translate_age,
    translate_belt,
    translate_gender,
    translate_weight,
)


NO_GI_TOKENS = ("no gi", "no-gi", "sem kimono")
WEIGHT_PAREN_RE = re.compile(r"\s+\(.*\)\s*$")
YEAR_SUFFIX_RE = re.compile(r"\s+(\d{4})\s*$")
SLUG_RE = re.compile(r"[^a-z0-9]+")

# Tournaments with no match data fall back to these canonical dates.
# Keys are matched against the event name with its trailing 4-digit year stripped.
MAJOR_EVENT_DATES = {
    "World Master Jiu-Jitsu IBJJF Championship": (9, 1),
    "European IBJJF Jiu-Jitsu No-Gi Championship": (11, 1),
    "Pan IBJJF Jiu-Jitsu No-Gi Championship": (10, 1),
    "Campeonato Brasileiro de Jiu-Jitsu Sem Kimono": (7, 1),
    "World IBJJF Jiu-Jitsu No-Gi Championship": (12, 1),
    "World IBJJF Jiu-Jitsu Championship": (6, 1),
    "European IBJJF Jiu-Jitsu Championship": (1, 15),
    "Pan IBJJF Jiu-Jitsu Championship": (3, 15),
    "Campeonato Brasileiro de Jiu-Jitsu": (5, 1),
}
# Longest-prefix-first so "Campeonato Brasileiro de Jiu-Jitsu Sem Kimono" wins
# over "Campeonato Brasileiro de Jiu-Jitsu".
_MAJOR_EVENT_KEYS_BY_LEN = sorted(MAJOR_EVENT_DATES.keys(), key=len, reverse=True)


def is_no_gi_event(event_name: str) -> bool:
    """gi/no-gi is determined solely from the tournament name, never the division string."""
    lower = event_name.lower()
    return any(token in lower for token in NO_GI_TOKENS)


def parse_division_parts(raw_division: str) -> Optional[tuple]:
    """Return (belt, age, gender, weight) tuple or None if unparseable."""
    cleaned = WEIGHT_PAREN_RE.sub("", raw_division).strip()
    parts = [p.strip() for p in cleaned.split("/")]
    if len(parts) < 4:
        return None
    age = belt = weight = gender = None
    for part in parts:
        if age is None:
            try:
                age = translate_age(part)
                continue
            except ValueError:
                pass
        if belt is None:
            try:
                belt = translate_belt(part.upper())
                continue
            except ValueError:
                pass
        if weight is None:
            try:
                weight = translate_weight(part)
                continue
            except ValueError:
                pass
        if gender is None:
            try:
                gender = translate_gender(part)
                continue
            except ValueError:
                pass
    if not (age and belt and weight and gender):
        return None
    return belt, age, gender, weight


def build_division_cache(session) -> dict:
    """Load every Division once into a dict keyed by (belt, age, gender, weight, gi).

    Divisions are effectively static config — fewer than ~1000 rows. Reuse this
    cache across many parse_and_resolve_division calls to avoid per-row queries.
    """
    cache = {}
    for d in session.query(Division).all():
        cache[(d.belt, d.age, d.gender, d.weight, d.gi)] = d
    return cache


def parse_and_resolve_division(
    session, raw_division: str, gi: bool, division_cache: Optional[dict] = None
) -> Optional[Division]:
    """Resolve a raw division string + gi flag (from event name!) to a Division row.

    Pass `division_cache` (from `build_division_cache`) to avoid per-row queries.
    """
    parts = parse_division_parts(raw_division)
    if not parts:
        return None
    belt, age, gender, weight = parts
    if division_cache is not None:
        return division_cache.get((belt, age, gender, weight, gi))
    return (
        session.query(Division)
        .filter(
            Division.belt == belt,
            Division.age == age,
            Division.gender == gender,
            Division.weight == weight,
            Division.gi == gi,
        )
        .one_or_none()
    )


def find_or_create_team(session, raw_team_name: str) -> Team:
    """Look up a team by normalized name; create it if missing. Caller commits."""
    norm = normalize(raw_team_name)
    team = session.query(Team).filter(Team.normalized_name == norm).first()
    if team:
        return team
    team = Team(name=raw_team_name, normalized_name=norm)
    session.add(team)
    session.flush()
    return team


def find_event(
    session, raw_event_name: str, event_ibjjf_id: Optional[str]
) -> Optional[Event]:
    """Resolve a raw tournament name (and optional ibjjf_id) to an Event row.

    Cascade: ibjjf_id -> exact name -> normalized name -> prefix match
    (the prefix match absorbs our `<name> (BJJHeroes)` / `<name> (Flo)` suffix
    convention; stored names have a leading space before the parenthesised suffix
    so a plain prefix wildcard handles it).
    """
    if event_ibjjf_id:
        event = session.query(Event).filter(Event.ibjjf_id == event_ibjjf_id).first()
        if event:
            return event

    event = session.query(Event).filter(Event.name == raw_event_name).first()
    if event:
        return event

    norm = normalize(raw_event_name)
    event = session.query(Event).filter(Event.normalized_name == norm).first()
    if event:
        return event

    prefix_matches = (
        session.query(Event).filter(Event.name.like(raw_event_name + "%")).all()
    )
    if not prefix_matches:
        return None
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    return min(prefix_matches, key=lambda e: len(e.name))


def _make_event_slug(name: str) -> str:
    base = SLUG_RE.sub("-", name.lower()).strip("-")
    return base or "event"


def create_medals_only_event(session, raw_event_name: str) -> Event:
    """Create an Event row with medals_only=True for a tournament we have no brackets for.

    Raises ValueError if the year can't be parsed from the trailing of the name.
    """
    year_match = YEAR_SUFFIX_RE.search(raw_event_name)
    if not year_match:
        raise ValueError(
            f"Cannot parse trailing year from event name: {raw_event_name!r}"
        )
    base_slug = _make_event_slug(raw_event_name)
    slug = base_slug
    n = 2
    while session.query(Event.id).filter(Event.slug == slug).first() is not None:
        slug = f"{base_slug}-{n}"
        n += 1
    event = Event(
        name=raw_event_name,
        normalized_name=normalize(raw_event_name),
        slug=slug,
        medals_only=True,
    )
    session.add(event)
    session.flush()
    return event


def _event_default_date(raw_event_name: str) -> Optional[datetime]:
    year_match = YEAR_SUFFIX_RE.search(raw_event_name)
    if not year_match:
        return None
    year = int(year_match.group(1))
    prefix = raw_event_name[: year_match.start()].rstrip()
    for key in _MAJOR_EVENT_KEYS_BY_LEN:
        if prefix == key:
            month, day = MAJOR_EVENT_DATES[key]
            return datetime(year, month, day)
    return None


def compute_happened_at(
    session, athlete_id, event: Event, raw_event_name: str
) -> datetime:
    """Spec precedence:
    1) athlete's last match in this event
    2) any athlete's last match in this event
    3) the major-event hardcoded date for this name prefix, if applicable
    4) Jan 1 of the event's year
    """
    last_match = (
        session.query(Match.happened_at)
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .filter(
            Match.event_id == event.id,
            MatchParticipant.athlete_id == athlete_id,
        )
        .order_by(Match.happened_at.desc())
        .first()
    )
    if last_match:
        return last_match[0]
    last_event_match = (
        session.query(Match.happened_at)
        .filter(Match.event_id == event.id)
        .order_by(Match.happened_at.desc())
        .first()
    )
    if last_event_match:
        return last_event_match[0]
    default_date = _event_default_date(raw_event_name)
    if default_date:
        return default_date
    year_match = YEAR_SUFFIX_RE.search(raw_event_name)
    if year_match:
        return datetime(int(year_match.group(1)), 1, 1)
    raise ValueError(
        f"Cannot determine happened_at for event {raw_event_name!r} "
        "(no matches and no parseable year)"
    )


def compute_default_gold(session, result_medal: ResultMedal) -> bool:
    """True iff place==1 AND no other rows in result_medals share (event_name, division)."""
    if result_medal.place != 1:
        return False
    sibling = (
        session.query(ResultMedal.id)
        .filter(
            ResultMedal.event_name == result_medal.event_name,
            ResultMedal.division == result_medal.division,
            ResultMedal.id != result_medal.id,
        )
        .first()
    )
    return sibling is None


def medal_already_exists(session, athlete_id, event_id, division_id) -> bool:
    """Idempotency guard. Same (athlete, event, division) can only hold one medal."""
    return (
        session.query(Medal.id)
        .filter(
            Medal.athlete_id == athlete_id,
            Medal.event_id == event_id,
            Medal.division_id == division_id,
        )
        .first()
        is not None
    )


def insert_medal(
    session,
    *,
    athlete_id,
    event_id,
    division_id,
    team_id,
    place,
    happened_at,
    default_gold,
    imported_via,
) -> Medal:
    """Insert a Medal row with audit metadata. Caller is responsible for commit."""
    medal = Medal(
        athlete_id=athlete_id,
        event_id=event_id,
        division_id=division_id,
        team_id=team_id,
        place=place,
        happened_at=happened_at,
        default_gold=default_gold,
        imported_via=imported_via,
        imported_at=datetime.utcnow(),
    )
    session.add(medal)
    session.flush()
    return medal


# ---------------------------------------------------------------------------
# Belt-rank filter
# ---------------------------------------------------------------------------


def belt_rank(belt: str) -> Optional[int]:
    """Rank within belt_order, or None for belts not in the ladder (coral/red competes at BLACK)."""
    try:
        return belt_order.index(belt)
    except ValueError:
        return None


def athlete_belt_bounds_at(session, athlete_id, when: datetime) -> tuple:
    """Return (lo, hi) — bounds on the athlete's possible belt rank at `when`.

    lo = max belt rank seen at or before `when` (belts only go up, so the athlete
         cannot have been *lower* than their highest belt up to that date)
    hi = min belt rank seen at or after `when` (the athlete cannot have already
         been *higher* than the lowest belt they're at later)
    Either side `None` if no matches on that side.
    """
    rows = (
        session.query(Division.belt, Match.happened_at)
        .join(Match, Match.division_id == Division.id)
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .filter(MatchParticipant.athlete_id == athlete_id)
        .all()
    )
    lo, hi = None, None
    for belt, happened_at in rows:
        rank = belt_rank(belt)
        if rank is None:
            continue
        if happened_at <= when:
            lo = rank if lo is None else max(lo, rank)
        if happened_at >= when:
            hi = rank if hi is None else min(hi, rank)
    return lo, hi


def medal_is_plausible(
    session, athlete_id, medal_belt: str, medal_date: datetime
) -> bool:
    """Hard filter: candidate medal's belt must fit the athlete's known belt bounds.

    Returns True when there's no constraint (athlete has no matches, or the
    medal's belt isn't in our ladder — e.g. coral/red).
    """
    rank = belt_rank(medal_belt)
    if rank is None:
        return True
    lo, hi = athlete_belt_bounds_at(session, athlete_id, medal_date)
    if lo is not None and rank < lo:
        return False
    if hi is not None and rank > hi:
        return False
    return True


def athlete_known_genders(session, athlete_id) -> set:
    """Set of division genders the athlete has competed in (Match) or medaled in (Medal).

    Empty set means we have no data for this athlete.
    """
    genders = set()
    via_matches = (
        session.query(Division.gender)
        .join(Match, Match.division_id == Division.id)
        .join(MatchParticipant, MatchParticipant.match_id == Match.id)
        .filter(MatchParticipant.athlete_id == athlete_id)
        .distinct()
    )
    via_medals = (
        session.query(Division.gender)
        .join(Medal, Medal.division_id == Division.id)
        .filter(Medal.athlete_id == athlete_id)
        .distinct()
    )
    for (g,) in via_matches.all():
        genders.add(g)
    for (g,) in via_medals.all():
        genders.add(g)
    return genders


def gender_is_plausible(session, athlete_id, medal_gender: str) -> bool:
    """Hard filter: an athlete who has only competed/medaled in male divisions
    cannot receive a female medal, and vice versa.

    Returns True when we have no data for this athlete (unconstrained).
    """
    known = athlete_known_genders(session, athlete_id)
    if not known:
        return True
    return medal_gender in known


# ---------------------------------------------------------------------------
# Fuzzy name scoring
# ---------------------------------------------------------------------------


def name_score(
    query_name: str,
    candidate_name: str,
    candidate_personal_name: Optional[str] = None,
) -> int:
    """Token-sort-ratio score of normalized query vs candidate (and personal_name if set).

    We use `token_sort_ratio` rather than `token_ratio` so that a short subset name
    (e.g. "Eduardo Garcia") doesn't score 100 against a longer superset
    ("Hugo Eduardo Mercado Garcia"). token_ratio = max(sort, set), and the set
    component returns 100 for any subset — which destroys the auto-import gap rule
    when two candidates share a last name with the query.
    """
    from rapidfuzz import fuzz

    q = normalize(query_name)
    best = fuzz.token_sort_ratio(q, normalize(candidate_name))
    if candidate_personal_name:
        alt = fuzz.token_sort_ratio(q, normalize(candidate_personal_name))
        if alt > best:
            best = alt
    return int(best)


# ---------------------------------------------------------------------------
# Scanner for "events with brackets that are missing medals" (Problem 2)
# ---------------------------------------------------------------------------


EVENT_SUFFIX_RE = re.compile(r"\s+\([^()]*\)\s*$")


def _strip_event_suffix(event_name: str) -> str:
    return EVENT_SUFFIX_RE.sub("", event_name).strip()


def find_result_medals_for_event(session, event: Event) -> list:
    """Return ResultMedal rows that belong to this Event.

    Tries event_ibjjf_id first, then exact name, then a suffix-stripped exact name
    (so an event named e.g. 'Pan ... 2024 (BJJHeroes)' still matches the IBJJF row
    'Pan ... 2024').
    """
    rows = []
    seen_ids = set()

    def _add(row_list):
        for r in row_list:
            if r.id not in seen_ids:
                seen_ids.add(r.id)
                rows.append(r)

    if event.ibjjf_id:
        _add(
            session.query(ResultMedal)
            .filter(ResultMedal.event_ibjjf_id == event.ibjjf_id)
            .all()
        )
        if rows:
            return rows

    _add(session.query(ResultMedal).filter(ResultMedal.event_name == event.name).all())

    stripped = _strip_event_suffix(event.name)
    if stripped and stripped != event.name:
        _add(
            session.query(ResultMedal).filter(ResultMedal.event_name == stripped).all()
        )

    return rows


def find_events_with_matches_in_range(
    session, since: datetime, until: datetime
) -> list:
    """Events with at least one Match in [since, until] that aren't medals-only.

    `medals_only` is nullable — legacy bracket-imported events have NULL.
    Treat NULL the same as False (i.e., "has bracket data").
    """
    from sqlalchemy import or_

    return (
        session.query(Event)
        .join(Match, Match.event_id == Event.id)
        .filter(
            or_(Event.medals_only.is_(False), Event.medals_only.is_(None)),
            Match.happened_at >= since,
            Match.happened_at <= until,
        )
        .distinct()
        .order_by(Event.name)
        .all()
    )


def _athlete_candidates_at_event(session, event_id):
    """Athletes with any presence at this event — MatchParticipant OR Medal.

    Broader than just "competed in this exact division" so we catch:
      - default_gold-only winners (no Match exists, but a Medal does after prior imports)
      - cross-division entrants (competed in their weight class, default_gold in Open Class)
      - half-imported events where some divisions' brackets weren't captured
    Belt-rank plausibility downstream keeps wrong-belt namesakes from being mismatched.
    """
    from models import Athlete

    via_matches = (
        session.query(Athlete)
        .join(MatchParticipant, MatchParticipant.athlete_id == Athlete.id)
        .join(Match, Match.id == MatchParticipant.match_id)
        .filter(Match.event_id == event_id)
    )
    via_medals = (
        session.query(Athlete)
        .join(Medal, Medal.athlete_id == Athlete.id)
        .filter(Medal.event_id == event_id)
    )
    # Two simple queries + Python dedup is cheaper than a UNION with a JOIN
    # back to athletes on this DB.
    seen = {}
    for a in via_matches.all():
        seen[a.id] = a
    for a in via_medals.all():
        seen.setdefault(a.id, a)
    return list(seen.values())


def scan_event_for_missing_medals(
    session,
    event: Event,
    *,
    fuzzy: bool = False,
    auto_threshold: int = 92,
    gap_threshold: int = 8,
    soft_threshold: int = 75,
    soft_gap_threshold: int = 12,
    division_cache: Optional[dict] = None,
) -> list:
    """For one event, return a list of per-result_medal status dicts.

    Each entry:
      {
        "result_medal": ResultMedal,
        "division": Division | None,
        "status": "matched" | "ambiguous" | "no_match" | "no_division" | "already_imported",
        "matched_athlete": Athlete | None,
        "alternatives": [{"athlete": Athlete, "score": int}, ...],
      }

    `fuzzy=False`: name match is exact-normalized against the per-(event,division)
                   candidate set. `fuzzy=True`: rapidfuzz token_ratio with auto/gap thresholds.

    Team and happened_at are resolved lazily at import time, not here — so scans
    are cheap and have no side effects.
    """
    if division_cache is None:
        division_cache = build_division_cache(session)

    gi = not is_no_gi_event(event.name)
    entries = []
    raw_medals = find_result_medals_for_event(session, event)

    # Per-event caches.
    candidates = _athlete_candidates_at_event(session, event.id)
    belt_bounds_cache = {}  # athlete_id -> (lo, hi)
    gender_cache = {}  # athlete_id -> set of known genders

    # event_when is used for belt-plausibility on candidates. Compute once.
    last_match_row = (
        session.query(Match.happened_at)
        .filter(Match.event_id == event.id)
        .order_by(Match.happened_at.desc())
        .first()
    )
    event_when = last_match_row[0] if last_match_row else datetime.utcnow()

    # Cache existing (athlete_id) -> set of division_ids already medaled at this event.
    existing_pairs = set(
        (m.athlete_id, m.division_id)
        for m in session.query(Medal.athlete_id, Medal.division_id)
        .filter(Medal.event_id == event.id)
        .all()
    )

    def _belt_bounds(athlete_id):
        if athlete_id not in belt_bounds_cache:
            belt_bounds_cache[athlete_id] = athlete_belt_bounds_at(
                session, athlete_id, event_when
            )
        return belt_bounds_cache[athlete_id]

    def _known_genders(athlete_id):
        if athlete_id not in gender_cache:
            gender_cache[athlete_id] = athlete_known_genders(session, athlete_id)
        return gender_cache[athlete_id]

    def _plausible(athlete_id, belt, gender):
        # Gender check (hard): an athlete who only competed in male divisions
        # cannot receive a female medal. Empty known-set = unconstrained.
        known_genders = _known_genders(athlete_id)
        if known_genders and gender not in known_genders:
            return False
        # Belt-rank check: medal's belt must fit the athlete's bounds at event_when.
        rank = belt_rank(belt)
        if rank is None:
            return True
        lo, hi = _belt_bounds(athlete_id)
        if lo is not None and rank < lo:
            return False
        if hi is not None and rank > hi:
            return False
        return True

    for rm in raw_medals:
        division = parse_and_resolve_division(
            session, rm.division, gi, division_cache=division_cache
        )
        if division is None:
            entries.append(
                {
                    "result_medal": rm,
                    "division": None,
                    "status": "no_division",
                    "matched_athlete": None,
                    "alternatives": [],
                }
            )
            continue

        # Belt + gender pre-filter: drop candidates whose known belt bounds rule
        # out this medal's belt OR whose known gender is the opposite of the
        # medal's division. Athletes with no history pass through.
        plausible_candidates = [
            a for a in candidates if _plausible(a.id, division.belt, division.gender)
        ]

        rm_normalized = normalize(rm.athlete_name)

        matched_athlete = None
        alternatives = []

        if not fuzzy:
            exact_hits = [
                a
                for a in plausible_candidates
                if a.normalized_name == rm_normalized
                or (a.normalized_personal_name == rm_normalized)
            ]
            if len(exact_hits) == 1:
                matched_athlete = exact_hits[0]
            elif len(exact_hits) > 1:
                alternatives = [{"athlete": a, "score": 100} for a in exact_hits]
        else:
            scored = []
            for a in plausible_candidates:
                s = name_score(rm.athlete_name, a.name, a.personal_name)
                scored.append((s, a))
            scored.sort(key=lambda t: t[0], reverse=True)
            if scored:
                best_score, best = scored[0]
                runner_up = scored[1][0] if len(scored) > 1 else 0
                gap = best_score - runner_up
                # Two confidence tiers, either is sufficient:
                #   - HIGH absolute score with a modest gap (near-exact match)
                #   - MID score with a wide gap (e.g. extra middle name or abbreviation
                #     drops the score below 92 but the runner-up is still far behind)
                high = best_score >= auto_threshold and gap >= gap_threshold
                soft = best_score >= soft_threshold and gap >= soft_gap_threshold
                if high or soft:
                    matched_athlete = best
                alternatives = [{"athlete": a, "score": s} for s, a in scored[:5]]

        if matched_athlete is None:
            status = "ambiguous" if len(alternatives) > 1 else "no_match"
            entries.append(
                {
                    "result_medal": rm,
                    "division": division,
                    "status": status,
                    "matched_athlete": None,
                    "alternatives": alternatives,
                }
            )
            continue

        if (matched_athlete.id, division.id) in existing_pairs:
            entries.append(
                {
                    "result_medal": rm,
                    "division": division,
                    "status": "already_imported",
                    "matched_athlete": matched_athlete,
                    "alternatives": [],
                }
            )
            continue

        entries.append(
            {
                "result_medal": rm,
                "division": division,
                "status": "matched",
                "matched_athlete": matched_athlete,
                "alternatives": [],
            }
        )

    return entries
