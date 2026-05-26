"""IBJJF seeding-points calculator.

Given the registration list for a single division, contains utilities that populate
each row with seeding-related fields (currently: ``points`` and ``open_class_points``)
according to the IBJJF's per-category, per-season, per-star, per-weight
points scheme, and sort the rows by those points.
"""

import math
import re
import zlib
from collections import Counter
from datetime import datetime

from sqlalchemy.sql import func, or_

from extensions import db
from models import Medal, Match, Division, Event, RegistrationLink, Suspension
from constants import (
    ADULT,
    BLACK,
    BROWN,
    JUVENILE,
    JUVENILE_1,
    JUVENILE_2,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
    weight_class_order,
)


SEEDING_ADULT_AGES = frozenset([ADULT])
# Juvenile, Juvenile 1, and Juvenile 2 share a points pool that does NOT
# carry into adult.
SEEDING_JUVENILE_AGES = frozenset([JUVENILE, JUVENILE_1, JUVENILE_2])
# Ordered young -> old; masters count their own level and every level below it,
# plus adult (but not juvenile).
SEEDING_MASTER_AGES_ORDERED = (
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
)
SEEDING_MASTER_AGES = frozenset(SEEDING_MASTER_AGES_ORDERED)

# Normal weight classes in order (Rooster -> Ultra Heavy) and the open-class set.
SEEDING_NORMAL_WEIGHTS_ORDERED = tuple(weight_class_order)
SEEDING_OPEN_CLASS_WEIGHTS = frozenset([OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY])

# Base names of the "Worlds" event whose start date defines each category's
# season boundaries. A season *begins at* the start of Worlds: a medal earned
# on the first day of Worlds 2025 is in the 2025-2026 season; one earned the
# day before falls in the previous season.
WORLDS_BASE_ADULT_GI = "World IBJJF Jiu-Jitsu Championship"
WORLDS_BASE_MASTERS_GI = "World Master IBJJF Jiu-Jitsu Championship"
WORLDS_BASE_NOGI = "World IBJJF Jiu-Jitsu No-Gi Championship"

# Historical-Worlds patterns, including legacy naming used in events before
# the 2022 rebrand ("World Jiu-Jitsu IBJJF Championship YYYY"). Used by the
# black-belt-specific seeding queries that need to look at ANY past Worlds,
# not just those inside the regular 3-season window.
WORLDS_BASES_ADULT_GI = (
    WORLDS_BASE_ADULT_GI,
    "World Jiu-Jitsu IBJJF Championship",
)
WORLDS_BASES_ADULT_NOGI = (
    WORLDS_BASE_NOGI,
    "World Jiu-Jitsu No-Gi IBJJF Championship",
)
# Gi Master Worlds is a *separate* event from gi adult Worlds. In no-gi
# there is no separate Master Worlds; master divisions are hosted inside
# the regular no-gi Worlds event — so no-gi master-title lookups use
# ``WORLDS_BASES_ADULT_NOGI`` filtered by ``Division.age``.
WORLDS_BASES_MASTERS_GI = (
    WORLDS_BASE_MASTERS_GI,
    "World Master Jiu-Jitsu IBJJF Championship",
)

# Grand Slam event bases per category, in calendar order
# (Euros, Pans, Brasileiros, Worlds). The current Grand Slam "season" is
# the most recent edition of each; multipliers (3x/2x/1x) apply per event
# type based on recency within that type, independent of the regular season.
GRAND_SLAM_BASES_ADULT_GI = (
    "European IBJJF Jiu-Jitsu Championship",
    "Pan IBJJF Jiu-Jitsu Championship",
    "Campeonato Brasileiro de Jiu-Jitsu",
    "World IBJJF Jiu-Jitsu Championship",
)
GRAND_SLAM_BASES_MASTERS_GI = (
    "European IBJJF Jiu-Jitsu Championship",
    "Pan IBJJF Jiu-Jitsu Championship",
    "Campeonato Brasileiro de Jiu-Jitsu",
    "World Master IBJJF Jiu-Jitsu Championship",
)
GRAND_SLAM_BASES_NOGI = (
    "European IBJJF Jiu-Jitsu No-Gi Championship",
    "Pan IBJJF Jiu-Jitsu No-Gi Championship",
    "Campeonato Brasileiro de Jiu-Jitsu Sem Kimono",
    "World IBJJF Jiu-Jitsu No-Gi Championship",
)

# Per-place base values. Normal-weight medals use the smaller scale,
# open-class medals get a larger scale (and a flat 1.0 weight multiplier).
_WEIGHT_PLACE_POINTS = {1: 9, 2: 3, 3: 1}
_OPEN_PLACE_POINTS = {1: 13.5, 2: 4.5, 3: 1.5}
_VALID_MEDAL_PLACES = list(_WEIGHT_PLACE_POINTS.keys())

# How many recent calendar years to scan when locating event-year groups
# (Worlds editions / Grand Slam editions). 4 covers any "today" point in
# the year because at most the 3 most-recent past Worlds can span 4
# calendar years (e.g. the day before this year's Worlds, we still need
# 3 years back).
_EVENT_YEAR_LOOKBACK = 4

# Exclude IBJJF Crown events, which aren't real medals / don't count for points
_IBJJF_CROWN_EVENT_NAME_PATTERN = "ibjjf crown %"


def _normalize_event_name(name):
    """Match key for an Event.name. Lowercases, removes any parenthetical
    groups (source markers like ' (Flo)', ' (BJJHeroes)', ' (Archive)' and
    sub-event qualifiers like ' (Juvenil, Adulto e Master)'), and collapses
    runs of whitespace.
    """
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def _event_base(normalized_name):
    """Strip the trailing 4-digit year from a normalized event name, so
    ``'world ibjjf jiu-jitsu championship 2024'`` becomes
    ``'world ibjjf jiu-jitsu championship'``. Used as the year-agnostic key
    for star-rating lookups so a single dict entry covers every edition of
    the same tournament.
    """
    return re.sub(r"\s+\d{4}\s*$", "", normalized_name).strip()


def _build_star_table(entries):
    """Given ``(base_name, stars)`` entries, return a year-agnostic
    ``{normalized_base: stars}`` dict — lookups should strip the year from
    the medal's normalized event name first via :func:`_event_base`.
    """
    return {_normalize_event_name(base): stars for base, stars in entries}


# Alternate event-name bases that should be treated as the canonical
# event base for star-rating lookups and Grand Slam slot grouping.
# Each entry maps a canonical raw base name to a list of raw alias
# base names. Keep both forms raw here so they can be re-used directly
# by SQL ``LIKE`` filters; normalization is applied at lookup time.
_EVENT_BASE_ALIASES_BY_CANONICAL = {
    "Campeonato Brasileiro de Jiu-Jitsu Sem Kimono": [
        "Brazilian National Jiu-Jitsu No-Gi Championship",
    ],
}

# Reverse map: normalized alias base -> normalized canonical base.
_EVENT_BASE_ALIASES = {
    _normalize_event_name(alias): _normalize_event_name(canonical)
    for canonical, aliases in _EVENT_BASE_ALIASES_BY_CANONICAL.items()
    for alias in aliases
}


def _canonical_event_base(normalized_base):
    """Map an aliased event-name base to its canonical normalized form."""
    return _EVENT_BASE_ALIASES.get(normalized_base, normalized_base)


def _bases_with_aliases(canonical_base):
    """Return ``[canonical_base, *aliases]`` (raw names) so callers can run
    SQL ``LIKE`` filters across every known variant of an event.
    """
    return [
        canonical_base,
        *_EVENT_BASE_ALIASES_BY_CANONICAL.get(canonical_base, []),
    ]


# Keywords that identify a tournament whose medals never count toward
# seeding points for any other tournament.
_NONE_EVENT_KEYWORDS = ("portugal grand slam",)
_NONE_EVENT_RE = re.compile(
    r"(?:^|\W)(?:" + "|".join(re.escape(k) for k in _NONE_EVENT_KEYWORDS) + r")(?:$|\W)"
)
_SUL_BRASILEIRO_RE = re.compile(r"(?:^|\W)sul\s*-?\s*brasileiro(?:$|\W)")
_PORTUGUESE_CHAMPIONSHIP_RE = re.compile(
    r"(?:^|\W)campeonato portugu[eê]s(?: de jiu-jitsu)?\s+(\d{4})(?:$|\W)"
)

# Tournament classifications for scoring purposes:
#   "none"       — medals from these events never contribute to seeding
#                  points for any target tournament.
#   "ibjjf_only" — everything else. Always uses the IBJJF schedule.
TOURNAMENT_TYPE_NONE = "none"
TOURNAMENT_TYPE_IBJJF_ONLY = "ibjjf_only"


def _event_tournament_type(event_name):
    """Classify ``event_name`` as none or ibjjf-only."""
    if not event_name:
        return TOURNAMENT_TYPE_IBJJF_ONLY
    normalized = _normalize_event_name(event_name)
    if _NONE_EVENT_RE.search(normalized) or _SUL_BRASILEIRO_RE.search(normalized):
        return TOURNAMENT_TYPE_NONE
    portuguese_championship = _PORTUGUESE_CHAMPIONSHIP_RE.search(normalized)
    if portuguese_championship and int(portuguese_championship.group(1)) >= 2026:
        return TOURNAMENT_TYPE_NONE
    return TOURNAMENT_TYPE_IBJJF_ONLY


def _season_multiplier(seasons, happened_at):
    """Find the multiplier (n .. 1) for ``happened_at`` against ``seasons``
    (ordered newest -> oldest). Returns ``None`` when no season matches.
    """
    for i, (start, end) in enumerate(seasons):
        if start <= happened_at < end:
            return len(seasons) - i
    return None


def _suspension_ranges_by_athlete_id(rows):
    """Build ``{athlete_id: [(start_date, end_date), ...]}`` for the
    athletes in ``rows``. The Suspension table is small, so the whole
    thing is loaded and then filtered down to the relevant athletes
    (suspensions are stored keyed by athlete *name*).
    """
    name_to_id = {
        row["name"]: row["id"] for row in rows if row.get("name") and row.get("id")
    }
    if not name_to_id:
        return {}
    result = {}
    for s in db.session.query(
        Suspension.athlete_name, Suspension.start_date, Suspension.end_date
    ).all():
        aid = name_to_id.get(s.athlete_name)
        if aid is None:
            continue
        result.setdefault(aid, []).append((s.start_date, s.end_date))
    return result


def _medal_during_suspension(suspension_ranges, athlete_id, happened_at):
    """Mirror of the frontend ``isMedalDuringSuspension`` helper. Returns
    True when ``happened_at`` falls on or between any of the athlete's
    suspension start/end dates (inclusive, day-granularity).
    """
    if happened_at is None:
        return False
    ranges = suspension_ranges.get(athlete_id)
    if not ranges:
        return False
    medal_date = happened_at.date()
    for start, end in ranges:
        if start.date() <= medal_date <= end.date():
            return True
    return False


# Adult/Juvenile gi star tournaments. Base names are the *current* (post-2022)
# event-name forms from the events table, without year suffix and without any
# trailing source-marker parenthetical.
_ADULT_GI_TOURNAMENTS = [
    ("World IBJJF Jiu-Jitsu Championship", 7),
    ("European IBJJF Jiu-Jitsu Championship", 4),
    ("Pan IBJJF Jiu-Jitsu Championship", 4),
    ("Campeonato Brasileiro de Jiu-Jitsu", 4),
    ("Asian Jiu-Jitsu IBJJF Championship", 3),
    ("American National IBJJF Jiu-Jitsu Championship", 2),
    # BJJ Pro is multi-city; each city is its own event in the DB.
    ("Curitiba BJJ Pro IBJJF Championship", 2),
    ("Rio BJJ Pro IBJJF Championship", 2),
    ("São Paulo BJJ Pro IBJJF Championship", 2),
    ("Pan Pacific IBJJF Jiu-Jitsu Championship", 2),
    ("South American Jiu-Jitsu IBJJF Championship", 2),
    ("Campeonato Sul-Americano de Jiu-Jitsu", 2),
    ("Jiu-Jitsu CON International", 2),
]
STAR_RATINGS_ADULT_GI = _build_star_table(_ADULT_GI_TOURNAMENTS)

# Masters gi: adult gi minus World, plus World Master and Master International series.
_MASTERS_GI_TOURNAMENTS = [
    (name, stars)
    for name, stars in _ADULT_GI_TOURNAMENTS
    if name != "World IBJJF Jiu-Jitsu Championship"
] + [
    ("World Master IBJJF Jiu-Jitsu Championship", 7),
    # Master International series (all regions, both naming generations).
    ("Master International Jiu-Jitsu Championship - Asia", 4),
    ("Master International Jiu-Jitsu Championship - Europe", 4),
    ("Master International Jiu-Jitsu Championship - North America", 4),
    ("Master International Jiu-Jitsu Championship - South America", 4),
    ("Master International Jiu-Jitsu IBJJF Championship", 4),
    ("Master International Jiu-Jitsu IBJJF Championship – Asia", 4),
    ("Master International Jiu-Jitsu IBJJF Championship – Europe", 4),
    ("Master International Jiu-Jitsu IBJJF Championship – North America", 4),
    ("Master International Jiu-Jitsu IBJJF Championship – South America", 4),
]
STAR_RATINGS_MASTERS_GI = _build_star_table(_MASTERS_GI_TOURNAMENTS)

_NOGI_TOURNAMENTS = [
    ("World IBJJF Jiu-Jitsu No-Gi Championship", 7),
    ("European IBJJF Jiu-Jitsu No-Gi Championship", 4),
    ("Pan IBJJF Jiu-Jitsu No-Gi Championship", 4),
    ("Campeonato Brasileiro de Jiu-Jitsu Sem Kimono", 4),
    ("American National IBJJF Jiu-Jitsu No-Gi Championship", 2),
    ("Pan Pacific IBJJF Jiu-Jitsu No-Gi Championship", 2),
    ("South American Jiu-Jitsu IBJJF No-Gi Championship", 2),
    ("Campeonato Sul-Americano de Jiu-Jitsu No-Gi", 2),
    ("Jiu-Jitsu CON No-Gi International", 2),
]
STAR_RATINGS_NOGI = _build_star_table(_NOGI_TOURNAMENTS)

DEFAULT_STAR_RATING = 1


def _star_table_for_division(division_age, gi):
    """Pick the star table that applies to a medal won in a given division.

    Driven by the *medal's* division, not the tournament's: a master
    competing for seeding gets x7 for an adult-Worlds gold because it was
    won in an adult division (and there are no master divisions at adult
    Worlds).
    """
    if not gi:
        return STAR_RATINGS_NOGI
    if division_age in SEEDING_MASTER_AGES:
        return STAR_RATINGS_MASTERS_GI
    return STAR_RATINGS_ADULT_GI


def _seeding_category(age, gi):
    """Return the set of division ages whose medals contribute to this
    division's seeding pool, or None if the age has no defined category.

    Each (age, gi) bucket has its own pool of point-eligible medals.
    Season boundaries are handled separately in :func:`_recent_seasons`.
    """
    if age in SEEDING_ADULT_AGES:
        return SEEDING_ADULT_AGES
    if age in SEEDING_JUVENILE_AGES:
        return SEEDING_JUVENILE_AGES
    if age in SEEDING_MASTER_AGES:
        # Masters carry forward: adult medals plus every master level up to
        # and including their own (Master 1 -> Adult+M1; Master 3 -> Adult+M1+M2+M3).
        # Juvenile medals do not fold into masters.
        idx = SEEDING_MASTER_AGES_ORDERED.index(age)
        return SEEDING_ADULT_AGES | frozenset(SEEDING_MASTER_AGES_ORDERED[: idx + 1])
    return None


def _worlds_base_name(age, gi):
    """The base name of the Worlds event whose start dates anchor the season
    boundaries for this division's category.
    """
    if not gi:
        return WORLDS_BASE_NOGI
    if age in SEEDING_MASTER_AGES:
        return WORLDS_BASE_MASTERS_GI
    return WORLDS_BASE_ADULT_GI


def _weight_multipliers(division_weight):
    """Return {medal_weight: multiplier} for the *normal* weight classes that
    contribute points to this division. Open-class medals are tallied
    separately and are not included here.

    - Normal-weight division: 100% from the same weight, 50% from the
      adjacent (one above, one below) weights.
    - Open-class division: 100% from every normal weight class.
    """
    if division_weight in SEEDING_OPEN_CLASS_WEIGHTS:
        return {w: 1.0 for w in SEEDING_NORMAL_WEIGHTS_ORDERED}
    if division_weight not in SEEDING_NORMAL_WEIGHTS_ORDERED:
        return {}
    idx = SEEDING_NORMAL_WEIGHTS_ORDERED.index(division_weight)
    multipliers = {division_weight: 1.0}
    if idx > 0:
        multipliers[SEEDING_NORMAL_WEIGHTS_ORDERED[idx - 1]] = 0.5
    if idx + 1 < len(SEEDING_NORMAL_WEIGHTS_ORDERED):
        multipliers[SEEDING_NORMAL_WEIGHTS_ORDERED[idx + 1]] = 0.5
    return multipliers


def _event_year_groups(base, today, lookback=_EVENT_YEAR_LOOKBACK):
    """For events whose normalized name matches ``{base} {year}`` for some
    `year` in the lookback window ending at ``today.year``, group them by
    year and return ``{year: (event_ids, earliest_start_datetime)}`` for
    years that have started (at least one matching event with a recorded
    start <= today).

    ``base`` may be a single raw base name or an iterable of equivalent
    bases (e.g. canonical + aliases); events matching any of them share
    year slots so alias editions don't consume extra rolling-window slots.

    Duplicate source records that collide on the same (base, year) — e.g.
    ``Campeonato Brasileiro de Jiu-Jitsu 2023`` vs.
    ``Campeonato Brasileiro de Jiu-Jitsu (Juvenil, Adulto e Master) 2023 (Flo)``
    — collapse into a single year-group, so they don't consume multiple
    rolling-window slots.
    """
    bases = [base] if isinstance(base, str) else list(base)
    years = range(today.year - lookback + 1, today.year + 1)
    candidate_by_norm = {
        _normalize_event_name(f"{b} {year}"): year for b in bases for year in years
    }
    candidate_events = (
        db.session.query(Event.id, Event.name)
        .filter(or_(*[Event.name.like(f"{b}%") for b in bases]))
        .all()
    )
    events_by_year = {}
    for e in candidate_events:
        year = candidate_by_norm.get(_normalize_event_name(e.name))
        if year is not None:
            events_by_year.setdefault(year, []).append(e.id)
    if not events_by_year:
        return {}

    all_ids = [eid for eids in events_by_year.values() for eid in eids]
    # Earliest match per event = the day that edition started. Aggregation
    # collapses to one row per event (no cartesian product despite many
    # matches per event).
    start_rows = (
        db.session.query(
            Match.event_id,
            func.min(Match.happened_at).label("start"),
        )
        .filter(Match.event_id.in_(all_ids))
        .group_by(Match.event_id)
        .all()
    )
    eid_to_start = {r.event_id: r.start for r in start_rows if r.start is not None}

    result = {}
    for year, eids in events_by_year.items():
        starts_in_year = [
            eid_to_start[eid]
            for eid in eids
            if eid in eid_to_start and eid_to_start[eid] <= today
        ]
        if not starts_in_year:
            continue
        result[year] = (eids, min(starts_in_year))
    return result


def _registration_link_year_groups(base, today, lookback=_EVENT_YEAR_LOOKBACK):
    """Like :func:`_event_year_groups`, but uses upcoming registration-link
    start dates as season anchors.

    This is intentionally used only for regular season boundaries. A
    ``RegistrationLink`` does not represent a medal-results event, so it
    must not create Grand Slam medal-scoring slots.
    """
    bases = [base] if isinstance(base, str) else list(base)
    years = range(today.year - lookback + 1, today.year + 1)
    candidate_by_norm = {
        _normalize_event_name(f"{b} {year}"): year for b in bases for year in years
    }

    candidate_links = (
        db.session.query(RegistrationLink.name, RegistrationLink.event_start_date)
        .filter(
            or_(*[RegistrationLink.name.like(f"{b}%") for b in bases]),
            RegistrationLink.event_start_date.isnot(None),
            RegistrationLink.event_start_date <= today,
            or_(RegistrationLink.hidden.is_(False), RegistrationLink.hidden.is_(None)),
        )
        .all()
    )

    starts_by_year = {}
    for link in candidate_links:
        year = candidate_by_norm.get(_normalize_event_name(link.name))
        if year is None:
            continue
        start = link.event_start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        current = starts_by_year.get(year)
        if current is None or start < current:
            starts_by_year[year] = start

    return {year: ([], start) for year, start in starts_by_year.items()}


def _regular_season_year_groups(base, today):
    """Return event year groups for regular-season boundaries, preferring
    pulled result events and filling missing anchors from registration links
    when available.
    """
    result_groups = _event_year_groups(base, today)
    registration_groups = _registration_link_year_groups(base, today)
    for year, group in registration_groups.items():
        result_groups.setdefault(year, group)
    return result_groups


def _recent_seasons(age, gi, today, n=3):
    """Return (start, end) datetime pairs for the n most recent seasons,
    using the actual start date of the relevant Worlds event as each season
    boundary. A season begins at midnight of the day Worlds starts: a medal
    earned on that day is in the new season; one earned the day before is in
    the previous season.

    seasons[0] is the in-progress / most recent season; seasons[-1] is the
    oldest. The end of the in-progress season is left open (a far-future
    sentinel) since the next Worlds hasn't happened yet. Returns ``[]`` if
    no usable Worlds events are found in the DB.
    """
    year_groups = _regular_season_year_groups(_worlds_base_name(age, gi), today)
    if not year_groups:
        return []

    sorted_years = sorted(year_groups.keys(), reverse=True)[:n]
    starts = [
        year_groups[y][1].replace(hour=0, minute=0, second=0, microsecond=0)
        for y in sorted_years
    ]

    far_future = datetime(9999, 12, 31)
    seasons = []
    next_start = far_future
    for s in starts:
        seasons.append((s, next_start))
        next_start = s
    return seasons


def _grand_slam_bases(age, gi):
    """The four Grand Slam event base names that apply to this category."""
    if not gi:
        return GRAND_SLAM_BASES_NOGI
    if age in SEEDING_MASTER_AGES:
        return GRAND_SLAM_BASES_MASTERS_GI
    return GRAND_SLAM_BASES_ADULT_GI


def _grand_slam_event_multipliers(age, gi, today, n=3):
    """For each of the four Grand Slam events, find the n most recent
    year-editions whose start <= today and assign multipliers
    3x / 2x / 1x by recency *within that event type* — this is the IBJJF's
    rolling Grand Slam season ("After Pans occurs, the season includes
    [...] upcoming Pans; once Brazilian Nationals occurs, the season
    updates to include [...] subsequent Brazilian Nationals").

    All event_ids matching a given (base, year) candidate share the same
    multiplier so duplicate source records don't take up extra slots.
    Returns ``{event_id: multiplier}``.
    """
    result = {}
    for base in _grand_slam_bases(age, gi):
        year_groups = _regular_season_year_groups(_bases_with_aliases(base), today)
        if not year_groups:
            continue
        sorted_years = sorted(year_groups.keys(), reverse=True)[:n]
        for i, year in enumerate(sorted_years):
            mult = n - i  # 3x, 2x, 1x
            for eid in year_groups[year][0]:
                result[eid] = mult
    return result


def _adult_worlds_patterns(gi):
    """Naming patterns for the Worlds event that hosts adult-division titles
    in this gi/no-gi context."""
    return WORLDS_BASES_ADULT_GI if gi else WORLDS_BASES_ADULT_NOGI


def _master_worlds_patterns(gi):
    """Naming patterns for the Worlds event that hosts master-division
    titles. Gi has a dedicated Master Worlds; no-gi hosts master divisions
    inside the regular no-gi Worlds event.
    """
    return WORLDS_BASES_MASTERS_GI if gi else WORLDS_BASES_ADULT_NOGI


def _past_worlds_year_groups(patterns, today):
    """Return ``{year: (event_ids, earliest_start_datetime)}`` for *every*
    past Worlds edition whose name matches one of the given patterns —
    both the 2022+ naming and the pre-2022 legacy naming, when those are
    included in ``patterns``.

    Unlike :func:`_event_year_groups`, this has no lookback window: it
    walks the events table for any year matching any base pattern, so the
    caller can answer "did this athlete ever win a Worlds?" without a
    recency cap.
    """
    valid_bases = {_normalize_event_name(p) for p in patterns}

    candidate_events = (
        db.session.query(Event.id, Event.name)
        .filter(or_(*[Event.name.like(f"{p} %") for p in patterns]))
        .all()
    )

    events_by_year = {}
    year_re = re.compile(r"\s(\d{4})$")
    for e in candidate_events:
        norm = _normalize_event_name(e.name)
        if _event_base(norm) not in valid_bases:
            continue
        m = year_re.search(norm)
        if not m:
            continue
        events_by_year.setdefault(int(m.group(1)), []).append(e.id)
    if not events_by_year:
        return {}

    all_ids = [eid for eids in events_by_year.values() for eid in eids]
    start_rows = (
        db.session.query(
            Match.event_id,
            func.min(Match.happened_at).label("start"),
        )
        .filter(Match.event_id.in_(all_ids))
        .group_by(Match.event_id)
        .all()
    )
    eid_to_start = {r.event_id: r.start for r in start_rows if r.start is not None}

    result = {}
    for year, eids in events_by_year.items():
        starts_in_year = []
        for eid in eids:
            start = eid_to_start.get(eid)
            if start is None:
                # Legacy Worlds edition with no per-match timestamps in
                # the DB — assume it ran in early June of its named year
                # so historical titles still register.
                start = datetime(year, 6, 1)
            if start <= today:
                starts_in_year.append(start)
        if not starts_in_year:
            continue
        result[year] = (eids, min(starts_in_year))
    return result


def _title_weight_filter(weight):
    """SQLAlchemy clause restricting ``Division.weight`` for black-belt title
    queries. Regular divisions match only their exact weight; open-class
    divisions match any of the three open-class variants (so a competitor in
    Open Class Heavy gets credit for an Open Class gold, etc.).
    """
    if weight in SEEDING_OPEN_CLASS_WEIGHTS:
        return Division.weight.in_(list(SEEDING_OPEN_CLASS_WEIGHTS))
    return Division.weight == weight


def _adult_black_belt_seeding(athlete_ids, divdata, gi, today, suspension_ranges):
    """Compute the six adult-black-belt-only seeding fields per athlete.

    Returns ``{athlete_id: {field: value, ...}}``; only athletes who have at
    least one of the flags set appear in the dict. Athletes not present in
    the result should keep the default values initialized by the caller.

    World-title checks for the recency flags (``world_champion_recent``,
    ``world_champion_4_years_ago``, ``world_champion_5_years_ago``) and for
    ``previous_brown_world_champion`` are scoped to the current division's
    weight class — regular weights match exactly, open-class divisions match
    any open-class variant. ``former_world_champion`` is the athlete's
    most-recent black-belt Worlds gold year in **any** weight class.

    Fields:
      - ``world_champion_recent`` — gold at any of the 3 most-recent past
        Worlds, at the current weight class.
      - ``world_champion_4_years_ago`` — gold at the 4th most-recent past
        Worlds at the current weight class.
      - ``world_champion_5_years_ago`` — gold at the 5th most-recent past
        Worlds at the current weight class.
      - ``last_world_title_year`` — year of the athlete's most-recent Worlds
        gold at the current weight class, restricted to the 3 most-recent
        past Worlds (``None`` otherwise).
      - ``former_world_champion`` — most-recent black-belt Worlds gold year
        at any past Worlds, in any weight class (``None`` otherwise).
      - ``previous_brown_world_champion`` — gold at the single most-recent past
        Worlds in the **brown belt** adult division, at the current weight class.
    """
    if not athlete_ids:
        return {}

    year_groups = _past_worlds_year_groups(_adult_worlds_patterns(gi), today)
    if not year_groups:
        return {}

    # Recency rank by year: 0 = most recent past Worlds.
    sorted_years = sorted(year_groups.keys(), reverse=True)
    year_to_rank = {y: i for i, y in enumerate(sorted_years)}
    eid_to_year = {eid: y for y, (eids, _) in year_groups.items() for eid in eids}

    weight_filter = _title_weight_filter(divdata["weight"])

    # Black-belt adult golds at any past Worlds, in the current weight class —
    # drives the recency flags and ``last_world_title_year``.
    weight_rows = (
        db.session.query(Medal.athlete_id, Medal.event_id, Medal.happened_at)
        .join(Division, Medal.division_id == Division.id)
        .filter(
            Medal.athlete_id.in_(athlete_ids),
            Medal.event_id.in_(list(eid_to_year.keys())),
            Medal.place == 1,
            Medal.happened_at < today,
            Division.gi == gi,
            Division.age == ADULT,
            Division.belt == BLACK,
            weight_filter,
        )
        .all()
    )

    # Black-belt adult golds at any past Worlds, in *any* weight class — drives
    # ``former_world_champion``.
    any_weight_rows = (
        db.session.query(Medal.athlete_id, Medal.event_id, Medal.happened_at)
        .join(Division, Medal.division_id == Division.id)
        .filter(
            Medal.athlete_id.in_(athlete_ids),
            Medal.event_id.in_(list(eid_to_year.keys())),
            Medal.place == 1,
            Medal.happened_at < today,
            Division.gi == gi,
            Division.age == ADULT,
            Division.belt == BLACK,
        )
        .all()
    )

    # Brown-belt adult golds *only* at the single most-recent past Worlds,
    # in the current weight class.
    previous_event_ids = year_groups[sorted_years[0]][0]
    brown_winners = {
        r.athlete_id
        for r in (
            db.session.query(Medal.athlete_id, Medal.happened_at)
            .join(Division, Medal.division_id == Division.id)
            .filter(
                Medal.athlete_id.in_(athlete_ids),
                Medal.event_id.in_(previous_event_ids),
                Medal.place == 1,
                Medal.happened_at < today,
                Division.gi == gi,
                Division.age == ADULT,
                Division.belt == BROWN,
                weight_filter,
            )
            .all()
        )
        if not _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at)
    }

    weight_years_by_athlete = {}
    for r in weight_rows:
        if _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at):
            continue
        weight_years_by_athlete.setdefault(r.athlete_id, set()).add(
            eid_to_year[r.event_id]
        )

    any_weight_years_by_athlete = {}
    for r in any_weight_rows:
        if _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at):
            continue
        any_weight_years_by_athlete.setdefault(r.athlete_id, set()).add(
            eid_to_year[r.event_id]
        )

    result = {}
    affected = (
        set(weight_years_by_athlete) | set(any_weight_years_by_athlete) | brown_winners
    )
    for aid in affected:
        years_won = weight_years_by_athlete.get(aid, set())
        any_weight_years_won = any_weight_years_by_athlete.get(aid, set())
        ranks_won = {year_to_rank[y] for y in years_won}
        recent_years_won = {y for y in years_won if year_to_rank[y] <= 2}

        recent = bool(ranks_won & {0, 1, 2})
        four_yr = 3 in ranks_won
        five_yr = 4 in ranks_won

        result[aid] = {
            "world_champion_recent": recent,
            "last_world_title_year": (
                max(recent_years_won) if recent_years_won else None
            ),
            "world_champion_4_years_ago": four_yr,
            "world_champion_5_years_ago": five_yr,
            "former_world_champion": (
                max(any_weight_years_won) if any_weight_years_won else None
            ),
            "previous_brown_world_champion": aid in brown_winners,
        }
    return result


def _master_levels_up_to(master_age):
    """For a master division age, return ``[(level_num, master_age), ...]``
    for levels 1 .. current. e.g. for Master 3:
    ``[(1, Master 1), (2, Master 2), (3, Master 3)]``.
    """
    idx = SEEDING_MASTER_AGES_ORDERED.index(master_age)
    return [(i + 1, SEEDING_MASTER_AGES_ORDERED[i]) for i in range(idx + 1)]


def _master_black_belt_seeding(athlete_ids, divdata, gi, today, suspension_ranges):
    """Compute master-black-belt-only seeding flags per athlete.

    Returns ``{athlete_id: {field: value, ...}}``. Athletes not in the
    result keep the default values initialized by the caller.

    All title checks are scoped to the current division's weight class —
    regular weights match exactly, open-class divisions match any open-class
    variant.

    Fields (all booleans, indicating the *current* black-belt Worlds title
    in this weight class):
      - ``adult_world_champion`` — gold at the single most-recent past
        adult Worlds.
      - ``master_K_world_champion`` for K = 1 .. current master level —
        gold at the single most-recent past Master Worlds in the Master K
        division.

    Gi master tournaments look up master titles at the dedicated Master
    Worlds event. No-gi master tournaments look up master titles at the
    regular no-gi Worlds event (master divisions are hosted inline).
    """
    if not athlete_ids:
        return {}

    levels = _master_levels_up_to(divdata["age"])
    relevant_master_ages = [age for _, age in levels]
    weight_filter = _title_weight_filter(divdata["weight"])

    # Most-recent past adult Worlds (for the "adult_world_champion" check).
    adult_year_groups = _past_worlds_year_groups(_adult_worlds_patterns(gi), today)
    adult_event_ids = []
    if adult_year_groups:
        latest_adult_year = max(adult_year_groups.keys())
        adult_event_ids = list(adult_year_groups[latest_adult_year][0])

    adult_champs = set()
    if adult_event_ids:
        adult_champs = {
            r.athlete_id
            for r in (
                db.session.query(Medal.athlete_id, Medal.happened_at)
                .join(Division, Medal.division_id == Division.id)
                .filter(
                    Medal.athlete_id.in_(athlete_ids),
                    Medal.event_id.in_(adult_event_ids),
                    Medal.place == 1,
                    Medal.happened_at < today,
                    Division.gi == gi,
                    Division.age == ADULT,
                    Division.belt == BLACK,
                    weight_filter,
                )
                .all()
            )
            if not _medal_during_suspension(
                suspension_ranges, r.athlete_id, r.happened_at
            )
        }

    # Most-recent past master Worlds (different from adult Worlds in gi;
    # same event in no-gi).
    master_year_groups = _past_worlds_year_groups(_master_worlds_patterns(gi), today)
    master_event_ids = []
    if master_year_groups:
        latest_master_year = max(master_year_groups.keys())
        master_event_ids = list(master_year_groups[latest_master_year][0])

    master_champs_by_age = {}
    if master_event_ids:
        for r in (
            db.session.query(Medal.athlete_id, Medal.happened_at, Division.age)
            .join(Division, Medal.division_id == Division.id)
            .filter(
                Medal.athlete_id.in_(athlete_ids),
                Medal.event_id.in_(master_event_ids),
                Medal.place == 1,
                Medal.happened_at < today,
                Division.gi == gi,
                Division.age.in_(relevant_master_ages),
                Division.belt == BLACK,
                weight_filter,
            )
            .all()
        ):
            if _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at):
                continue
            master_champs_by_age.setdefault(r.age, set()).add(r.athlete_id)

    affected = set(adult_champs)
    for ids in master_champs_by_age.values():
        affected |= ids

    result = {}
    for aid in affected:
        info = {"adult_world_champion": aid in adult_champs}
        for level_num, master_age in levels:
            info[f"master_{level_num}_world_champion"] = aid in (
                master_champs_by_age.get(master_age, set())
            )
        result[aid] = info
    return result


def _compute_medal_contribution(
    place,
    weight,
    event_name,
    division_age,
    division_weight,
    gi,
    season_mult,
    weight_multipliers,
    division_is_open,
):
    """Pure computation of a single medal's seeding contribution.

    Returns ``(bucket, contribution, details)`` where:
      - ``bucket`` is ``"weight"`` or ``"open"`` (which accumulator the
        caller should add to). For non-open divisions, open-class medals
        fold into the ``"weight"`` bucket.
      - ``contribution`` is the float point value (``0.0`` if the medal
        contributes nothing — e.g. an adjacent-weight medal with weight
        multiplier 0).
      - ``details`` is a dict with the per-component values used to build
        the contribution: ``event_name``, ``division_age``,
        ``division_weight``, ``place``, ``base_points``, ``star``,
        ``season_mult``, ``weight_mult``, ``total``.
    """
    star_table = _star_table_for_division(division_age, gi)
    star_mult = star_table.get(
        _canonical_event_base(_event_base(_normalize_event_name(event_name))),
        DEFAULT_STAR_RATING,
    )
    if weight in SEEDING_OPEN_CLASS_WEIGHTS:
        base_points = _OPEN_PLACE_POINTS[place]
        weight_mult = 1.0
        contribution = base_points * season_mult * star_mult
        bucket = "open" if division_is_open else "weight"
    else:
        base_points = _WEIGHT_PLACE_POINTS[place]
        weight_mult = weight_multipliers.get(weight, 0.0)
        contribution = base_points * season_mult * weight_mult * star_mult
        bucket = "weight"
    details = {
        "event_name": event_name,
        "division_age": division_age,
        "division_weight": division_weight,
        "place": place,
        "base_points": base_points,
        "star": star_mult,
        "season_mult": season_mult,
        "weight_mult": weight_mult,
        "total": contribution,
    }
    return bucket, contribution, details


def _score_medal(
    weight_acc,
    open_acc,
    athlete_id,
    place,
    weight,
    event_name,
    division_age,
    gi,
    season_mult,
    weight_multipliers,
    division_is_open,
):
    """Apply place / star / weight / season multipliers to a single medal
    and add the resulting point value to the appropriate accumulator dict,
    in-place.

    Open-class medals are split into ``open_acc`` only when the division
    being seeded is itself open class; for non-open divisions they fold
    into ``weight_acc`` at a flat 1.0 weight multiplier (using the larger
    open-class place values), so the final ``points`` total reflects every
    medal that contributes seeding for this division.
    """
    bucket, contribution, _ = _compute_medal_contribution(
        place,
        weight,
        event_name,
        division_age,
        weight,
        gi,
        season_mult,
        weight_multipliers,
        division_is_open,
    )
    if weight not in SEEDING_OPEN_CLASS_WEIGHTS and not contribution:
        return
    target = open_acc if bucket == "open" else weight_acc
    target[athlete_id] = target.get(athlete_id, 0) + contribution


def _suspension_ranges_for_athlete_id(athlete_id):
    """Build the suspension-ranges dict for a single athlete id, mirroring
    the structure produced by :func:`_suspension_ranges_by_athlete_id` but
    looking up the athlete's name from the database instead of from a row
    set. Returns ``{}`` when the athlete has no suspensions on file.
    """
    from models import Athlete

    name_row = db.session.query(Athlete.name).filter(Athlete.id == athlete_id).first()
    if not name_row:
        return {}
    name = name_row.name
    result = {}
    for s in (
        db.session.query(
            Suspension.athlete_name, Suspension.start_date, Suspension.end_date
        )
        .filter(Suspension.athlete_name == name)
        .all()
    ):
        result.setdefault(athlete_id, []).append((s.start_date, s.end_date))
    return result


def _iter_regular_season_medal_rows(
    athlete_ids,
    divdata,
    gi,
    seasons,
    suspension_ranges,
    medal_cutoff,
    common_filters=None,
):
    """Yield ``(medal_row, season_mult)`` for every medal that contributes
    to the regular-season ``points`` bucket for the given athletes.

    Encapsulates all the gating logic — source-type filtering, suspension
    exclusion, season-window filtering, and season-multiplier lookup — that
    used to live inline in ``add_seeding_data``. The yielded rows are the
    canonical "which medals count toward this division's regular-season
    points" set, so both the existing pipeline and the per-athlete
    drill-down endpoint can be driven from this generator.
    """
    if not seasons:
        return
    if not athlete_ids:
        return

    age_filter = _seeding_category(divdata["age"], gi)
    if age_filter is None:
        return
    weight_multipliers = _weight_multipliers(divdata["weight"])
    weight_filter = list(weight_multipliers.keys()) + list(SEEDING_OPEN_CLASS_WEIGHTS)
    if not weight_filter:
        return

    if common_filters is None:
        common_filters = (
            Medal.athlete_id.in_(athlete_ids),
            Medal.place.in_(_VALID_MEDAL_PLACES),
            Division.gi == gi,
            Division.belt == divdata["belt"],
            Division.age.in_(age_filter),
            Division.weight.in_(weight_filter),
            Event.name.notilike(_IBJJF_CROWN_EVENT_NAME_PATTERN),
        )

    earliest_start = seasons[-1][0]
    # Cap at `medal_cutoff` so medals on or after the tournament start date
    # don't leak into the in-progress season (whose end is a far-future sentinel).
    latest_end = min(seasons[0][1], medal_cutoff)

    medal_rows = (
        db.session.query(
            Medal.athlete_id,
            Medal.place,
            Medal.happened_at,
            Division.age,
            Division.weight,
            Event.name.label("event_name"),
        )
        .join(Division, Medal.division_id == Division.id)
        .join(Event, Medal.event_id == Event.id)
        .filter(
            *common_filters,
            Medal.happened_at >= earliest_start,
            Medal.happened_at < latest_end,
        )
        .all()
    )
    for r in medal_rows:
        if _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at):
            continue
        source_type = _event_tournament_type(r.event_name)
        if source_type == TOURNAMENT_TYPE_NONE:
            continue
        season_mult = _season_multiplier(seasons, r.happened_at)
        if season_mult is None:
            continue
        yield r, season_mult


def _iter_grand_slam_medal_rows(
    athlete_ids,
    divdata,
    gi,
    gs_multipliers,
    suspension_ranges,
    medal_cutoff,
    common_filters=None,
):
    """Yield ``(medal_row, gs_mult)`` for every medal that contributes to
    the ``grand_slam_points`` bucket for the given athletes.

    Parallels :func:`_iter_regular_season_medal_rows`. The Grand Slam
    multiplier is driven by per-event-type recency from ``gs_multipliers``.
    """
    if not gs_multipliers:
        return
    if not athlete_ids:
        return

    age_filter = _seeding_category(divdata["age"], gi)
    if age_filter is None:
        return
    weight_multipliers = _weight_multipliers(divdata["weight"])
    weight_filter = list(weight_multipliers.keys()) + list(SEEDING_OPEN_CLASS_WEIGHTS)
    if not weight_filter:
        return

    if common_filters is None:
        common_filters = (
            Medal.athlete_id.in_(athlete_ids),
            Medal.place.in_(_VALID_MEDAL_PLACES),
            Division.gi == gi,
            Division.belt == divdata["belt"],
            Division.age.in_(age_filter),
            Division.weight.in_(weight_filter),
            Event.name.notilike(_IBJJF_CROWN_EVENT_NAME_PATTERN),
        )

    medal_rows = (
        db.session.query(
            Medal.athlete_id,
            Medal.place,
            Medal.event_id,
            Medal.happened_at,
            Division.age,
            Division.weight,
            Event.name.label("event_name"),
        )
        .join(Division, Medal.division_id == Division.id)
        .join(Event, Medal.event_id == Event.id)
        .filter(
            *common_filters,
            Medal.event_id.in_(list(gs_multipliers.keys())),
            Medal.happened_at < medal_cutoff,
        )
        .all()
    )
    for r in medal_rows:
        if _medal_during_suspension(suspension_ranges, r.athlete_id, r.happened_at):
            continue
        source_type = _event_tournament_type(r.event_name)
        if source_type == TOURNAMENT_TYPE_NONE:
            continue
        gs_mult = gs_multipliers[r.event_id]
        yield r, gs_mult


def _collect_bucket_details(medal_iter, gi, weight_multipliers, division_is_open):
    """Walk a ``(medal_row, season_mult)`` iterator and produce the
    drill-down payload for a single bucket: a list of detail dicts (sorted
    by ``happened_at`` descending, zero-contribution medals dropped) plus
    the integer per-accumulator totals (``points_total`` for the weight
    bucket, ``open_class_points_total`` for the open-class bucket).

    For non-open-class divisions, open-class medals fold into the
    ``"weight"`` bucket, so ``open_class_points_total`` will always be 0
    there — matching the main table's ``Open Pts`` column."""
    rows = []
    weight_total = 0.0
    open_total = 0.0
    for r, season_mult in medal_iter:
        bucket, contribution, details = _compute_medal_contribution(
            r.place,
            r.weight,
            r.event_name,
            r.age,
            r.weight,
            gi,
            season_mult,
            weight_multipliers,
            division_is_open,
        )
        if not contribution:
            continue
        details["bucket"] = bucket
        details["happened_at"] = (
            r.happened_at.isoformat() if r.happened_at is not None else None
        )
        rows.append(details)
        if bucket == "open":
            open_total += contribution
        else:
            weight_total += contribution
    rows.sort(key=lambda d: d.get("happened_at") or "", reverse=True)
    return {
        "medals": rows,
        "points_total": math.floor(weight_total),
        "open_class_points_total": math.floor(open_total),
    }


def collect_athlete_medal_details(athlete_id, divdata, gi, now=None, medal_cutoff=None):
    """Return the per-medal breakdown that drives the modal drill-down for
    a single athlete, split into the regular ``points`` and
    ``grand_slam_points`` buckets.

    Mirrors the setup ``add_seeding_data`` does — resolving season windows,
    weight multipliers, and suspension ranges — then walks
    :func:`_iter_regular_season_medal_rows` and
    :func:`_iter_grand_slam_medal_rows` for the athlete and computes each
    medal's contribution via :func:`_compute_medal_contribution`.

    Returns ``{"points": {...}, "grand_slam": {...}}`` where each bucket
    is ``{"medals": [...], "points_total": <int>, "open_class_points_total":
    <int>}``. ``medals`` is sorted by ``happened_at`` descending.
    Zero-contribution medals are dropped. ``points_total`` matches the
    main table's ``Pts`` / ``GS Pts`` column and ``open_class_points_total``
    matches ``Open Pts`` / ``GS Open Pts`` (always 0 for non-open
    divisions, since open-class medals fold into the weight bucket there).
    """
    empty = {"medals": [], "points_total": 0, "open_class_points_total": 0}
    age_filter = _seeding_category(divdata["age"], gi)
    if age_filter is None:
        return {"points": empty, "grand_slam": empty}

    weight_multipliers = _weight_multipliers(divdata["weight"])
    weight_filter = list(weight_multipliers.keys()) + list(SEEDING_OPEN_CLASS_WEIGHTS)
    if not weight_filter:
        return {"points": empty, "grand_slam": empty}
    division_is_open = divdata["weight"] in SEEDING_OPEN_CLASS_WEIGHTS

    if now is None:
        now = datetime.now()
    if medal_cutoff is None:
        medal_cutoff = now
    seasons = _recent_seasons(divdata["age"], gi, now, n=3)
    gs_multipliers = _grand_slam_event_multipliers(divdata["age"], gi, now, n=3)

    suspension_ranges = _suspension_ranges_for_athlete_id(athlete_id)

    points = _collect_bucket_details(
        _iter_regular_season_medal_rows(
            [athlete_id],
            divdata,
            gi,
            seasons,
            suspension_ranges,
            medal_cutoff,
        ),
        gi,
        weight_multipliers,
        division_is_open,
    )
    grand_slam = _collect_bucket_details(
        _iter_grand_slam_medal_rows(
            [athlete_id],
            divdata,
            gi,
            gs_multipliers,
            suspension_ranges,
            medal_cutoff,
        ),
        gi,
        weight_multipliers,
        division_is_open,
    )
    return {"points": points, "grand_slam": grand_slam}


def add_seeding_data(rows, divdata, gi, now=None, medal_cutoff=None):
    """Compute IBJJF seeding criteria for each competitor and attach to the row.

    Currently populates:
      - points: medal points from the 3 most recent seasons of the same
        gi/age category as this division. Normal-weight medals use base
        values 9 / 3 / 1 for 1st / 2nd / 3rd with weight multipliers (1.0
        same weight, 0.5 adjacent for normal-weight divisions; 1.0 every
        normal weight for open-class divisions). For *non-open-class*
        divisions, open-class medals also fold into ``points`` at base
        values 13.5 / 4.5 / 1.5 with a flat 1.0 weight multiplier — they
        are only broken out into ``open_class_points`` when the division
        being seeded is itself open class. Season multipliers are 3x / 2x
        / 1x and per-event star ratings are looked up against the medal's
        own division (so adult-division medals carried into masters
        seeding use the adult star table).
      - open_class_points: only populated for open-class divisions; the
        open-class medal contribution that ``points`` would otherwise have
        absorbed (base 13.5 / 4.5 / 1.5, flat 1.0 weight multiplier). For
        non-open divisions this stays 0.
      - grand_slam_points / grand_slam_open_class_points: same scoring as
        above (including the same "fold open into the regular bucket for
        non-open divisions" rule) but restricted to medals from Grand
        Slam events (Euros, Pans, Brasileiros, Worlds). The Grand Slam
        season multiplier is independent of the regular season: each of
        the four Grand Slam event types has its own rolling 3x / 2x / 1x
        window based on the recency of that specific event.

    Only for Adult / BLACK belt divisions, also populates six
    black-belt-specific fields (see :func:`_adult_black_belt_seeding`):
    ``world_champion_recent``, ``last_world_title_year``,
    ``world_champion_4_years_ago``, ``world_champion_5_years_ago``,
    ``former_world_champion``, ``previous_brown_world_champion``.

    Only for Master 1..7 / BLACK belt divisions, also populates
    ``adult_world_champion`` plus one ``master_K_world_champion`` flag for
    each level K = 1 .. current master level (see
    :func:`_master_black_belt_seeding`).

    Each medal's own ``Event.name`` determines whether that source medal is
    excluded from seeding points; all scoring medals use the IBJJF season
    schedule.

    ``now`` is the reference date used for season-window construction;
    defaults to ``datetime.now()``. ``medal_cutoff`` is the exclusive upper
    bound for medals included in the score and defaults to ``now``. The two
    dates differ for future registration pages: the season should be evaluated
    as of today, while medals still need to be capped at the target event
    start. Tests can pass fixed datetimes to make season rollover
    deterministic.

    Final values are floored to integers.
    """
    for row in rows:
        row["points"] = 0
        row["open_class_points"] = 0
        row["grand_slam_points"] = 0
        row["grand_slam_open_class_points"] = 0

    is_adult_black = divdata.get("age") == ADULT and divdata.get("belt") == BLACK
    is_master_black = (
        divdata.get("age") in SEEDING_MASTER_AGES and divdata.get("belt") == BLACK
    )
    master_levels = _master_levels_up_to(divdata["age"]) if is_master_black else []

    if is_adult_black:
        for row in rows:
            row["world_champion_recent"] = False
            row["last_world_title_year"] = None
            row["world_champion_4_years_ago"] = False
            row["world_champion_5_years_ago"] = False
            row["former_world_champion"] = None
            row["previous_brown_world_champion"] = False
    elif is_master_black:
        for row in rows:
            row["adult_world_champion"] = False
            for level_num, _ in master_levels:
                row[f"master_{level_num}_world_champion"] = False

    athlete_ids = list({row["id"] for row in rows if row.get("id")})
    if not athlete_ids:
        return

    age_filter = _seeding_category(divdata["age"], gi)
    if age_filter is None:
        return

    weight_multipliers = _weight_multipliers(divdata["weight"])
    weight_filter = list(weight_multipliers.keys()) + list(SEEDING_OPEN_CLASS_WEIGHTS)
    if not weight_filter:
        return
    division_is_open = divdata["weight"] in SEEDING_OPEN_CLASS_WEIGHTS

    if now is None:
        now = datetime.now()
    if medal_cutoff is None:
        medal_cutoff = now
    seasons = _recent_seasons(divdata["age"], gi, now, n=3)
    gs_multipliers = _grand_slam_event_multipliers(divdata["age"], gi, now, n=3)
    suspension_ranges = _suspension_ranges_by_athlete_id(rows)

    points_by_athlete = {}
    open_by_athlete = {}
    gs_points_by_athlete = {}
    gs_open_by_athlete = {}

    common_filters = (
        Medal.athlete_id.in_(athlete_ids),
        Medal.place.in_(_VALID_MEDAL_PLACES),
        Division.gi == gi,
        Division.belt == divdata["belt"],
        Division.age.in_(age_filter),
        Division.weight.in_(weight_filter),
        Event.name.notilike(_IBJJF_CROWN_EVENT_NAME_PATTERN),
    )

    # Regular points: medals inside the rolling-Worlds-anchored season
    # window.
    for r, season_mult in _iter_regular_season_medal_rows(
        athlete_ids,
        divdata,
        gi,
        seasons,
        suspension_ranges,
        medal_cutoff,
        common_filters,
    ):
        _score_medal(
            points_by_athlete,
            open_by_athlete,
            r.athlete_id,
            r.place,
            r.weight,
            r.event_name,
            r.age,
            gi,
            season_mult,
            weight_multipliers,
            division_is_open,
        )

    # Grand Slam points: medals at the most recent n editions of each Grand
    # Slam event, multipliers driven by per-event-type recency (not by the
    # regular season window).
    for r, gs_mult in _iter_grand_slam_medal_rows(
        athlete_ids,
        divdata,
        gi,
        gs_multipliers,
        suspension_ranges,
        medal_cutoff,
        common_filters,
    ):
        _score_medal(
            gs_points_by_athlete,
            gs_open_by_athlete,
            r.athlete_id,
            r.place,
            r.weight,
            r.event_name,
            r.age,
            gi,
            gs_mult,
            weight_multipliers,
            division_is_open,
        )

    if is_adult_black:
        bb_data = _adult_black_belt_seeding(
            athlete_ids, divdata, gi, now, suspension_ranges
        )
    elif is_master_black:
        bb_data = _master_black_belt_seeding(
            athlete_ids, divdata, gi, now, suspension_ranges
        )
    else:
        bb_data = {}

    for row in rows:
        aid = row.get("id")
        if aid is None:
            continue
        if aid in points_by_athlete:
            row["points"] = math.floor(points_by_athlete[aid])
        if aid in open_by_athlete:
            row["open_class_points"] = math.floor(open_by_athlete[aid])
        if aid in gs_points_by_athlete:
            row["grand_slam_points"] = math.floor(gs_points_by_athlete[aid])
        if aid in gs_open_by_athlete:
            row["grand_slam_open_class_points"] = math.floor(gs_open_by_athlete[aid])
        if aid in bb_data:
            row.update(bb_data[aid])


def add_estimated_seeds(rows, divdata):
    """Populate ``est_seed`` on each row with the 1-based ranking the athlete
    would have in this division based on the values produced by
    :func:`add_seeding_data`. Row order is preserved; ``est_seed`` and
    ``est_seed_tied`` are set on every row. ``est_seed_tied`` is True when
    the row's seed was decided only by the name-crc tie-break — i.e. some
    other row shares an identical key on every real seeding criterion — and
    so the relative order between those tied rows is arbitrary.
    Sort keys are descending (more is better -> lower seed number); for each
    criterion below, ties fall through to the next criterion.

    Six rankings, picked from ``divdata``:
      1. regular: ``grand_slam_points``, ``points``.
      2. regular open class: ``grand_slam_open_class_points``,
         ``grand_slam_points``, ``open_class_points``, ``points``.
      3. adult black belt: ``world_champion_recent``,
         ``last_world_title_year``, ``grand_slam_points``,
         ``world_champion_4_years_ago``, ``world_champion_5_years_ago``,
         ``previous_brown_world_champion``, ``former_world_champion`` year,
         ``points``.
      4. adult black belt open class: ``world_champion_recent``,
         ``last_world_title_year``, ``grand_slam_open_class_points``,
         ``grand_slam_points``, ``world_champion_4_years_ago``,
         ``world_champion_5_years_ago``, ``previous_brown_world_champion``,
         ``former_world_champion`` year, ``open_class_points``, ``points``.
      5. master black belt: ``adult_world_champion``,
         ``master_1_world_champion`` .. ``master_K_world_champion`` (K = this
         division's master level), ``grand_slam_points``, ``points``.
      6. master black belt open class: ``adult_world_champion``,
         ``master_1..K_world_champion``, ``grand_slam_open_class_points``,
         ``grand_slam_points``, ``open_class_points``, ``points``.
    """
    age = divdata.get("age")
    belt = divdata.get("belt")
    is_open = divdata.get("weight") in SEEDING_OPEN_CLASS_WEIGHTS
    is_adult_black = age == ADULT and belt == BLACK
    is_master_black = age in SEEDING_MASTER_AGES and belt == BLACK

    def tie_break(r):
        # Deterministic pseudo-random ordering on athletes who are otherwise
        # tied on every seeding criterion. Uses the athlete name (not id —
        # not every registrant matches a DB athlete) so it's stable across
        # runs and Python versions; crc32 is a fixed function unlike the
        # salted built-in hash().
        return zlib.crc32(r.get("name", "").encode("utf-8"))

    if is_adult_black and is_open:

        def keyfn(r):
            return (
                bool(r.get("world_champion_recent")),
                r.get("last_world_title_year") or 0,
                r.get("grand_slam_open_class_points", 0),
                r.get("grand_slam_points", 0),
                bool(r.get("world_champion_4_years_ago")),
                bool(r.get("world_champion_5_years_ago")),
                bool(r.get("previous_brown_world_champion")),
                r.get("former_world_champion") or 0,
                r.get("open_class_points", 0),
                r.get("points", 0),
                tie_break(r),
            )

    elif is_adult_black:

        def keyfn(r):
            return (
                bool(r.get("world_champion_recent")),
                r.get("last_world_title_year") or 0,
                r.get("grand_slam_points", 0),
                bool(r.get("world_champion_4_years_ago")),
                bool(r.get("world_champion_5_years_ago")),
                bool(r.get("previous_brown_world_champion")),
                r.get("former_world_champion") or 0,
                r.get("points", 0),
                tie_break(r),
            )

    elif is_master_black:
        master_fields = [
            f"master_{n}_world_champion" for n, _ in _master_levels_up_to(age)
        ]
        if is_open:

            def keyfn(r):
                return (
                    bool(r.get("adult_world_champion")),
                    *(bool(r.get(f)) for f in master_fields),
                    r.get("grand_slam_open_class_points", 0),
                    r.get("grand_slam_points", 0),
                    r.get("open_class_points", 0),
                    r.get("points", 0),
                    tie_break(r),
                )

        else:

            def keyfn(r):
                return (
                    bool(r.get("adult_world_champion")),
                    *(bool(r.get(f)) for f in master_fields),
                    r.get("grand_slam_points", 0),
                    r.get("points", 0),
                    tie_break(r),
                )

    elif is_open:

        def keyfn(r):
            return (
                r.get("grand_slam_open_class_points", 0),
                r.get("grand_slam_points", 0),
                r.get("open_class_points", 0),
                r.get("points", 0),
                tie_break(r),
            )

    else:

        def keyfn(r):
            return (
                r.get("grand_slam_points", 0),
                r.get("points", 0),
                tie_break(r),
            )

    ordered = sorted(range(len(rows)), key=lambda i: keyfn(rows[i]), reverse=True)
    for seed, i in enumerate(ordered, start=1):
        rows[i]["est_seed"] = seed

    # Mark rows whose seed was decided only by the name-crc tie-break — i.e.
    # at least one other row has an identical key on every real seeding
    # criterion. The frontend uses this to flag those seeds as ambiguous.
    keys_no_tiebreak = [keyfn(r)[:-1] for r in rows]
    key_counts = Counter(keys_no_tiebreak)
    for r, k in zip(rows, keys_no_tiebreak):
        r["est_seed_tied"] = key_counts[k] > 1


_IBJJF_SEED_LAYOUTS = {
    4: [(1, 4), (2, 3)],
    8: [(1, 8), (6, 4), (3, 5), (2, 7)],
    16: [
        (1, 16),
        (8, 12),
        (4, 14),
        (6, 10),
        (2, 15),
        (7, 11),
        (3, 13),
        (5, 9),
    ],
    32: [
        (1, 32),
        (16, 24),
        (8, 28),
        (12, 20),
        (4, 30),
        (14, 22),
        (6, 26),
        (10, 18),
        (2, 31),
        (15, 23),
        (7, 27),
        (11, 19),
        (3, 29),
        (13, 21),
        (5, 25),
        (9, 17),
    ],
    64: [
        (1, 64),
        (32, 48),
        (16, 56),
        (24, 40),
        (8, 60),
        (28, 44),
        (12, 52),
        (20, 36),
        (4, 62),
        (30, 46),
        (14, 54),
        (22, 38),
        (6, 58),
        (26, 42),
        (10, 50),
        (18, 34),
        (2, 63),
        (31, 47),
        (15, 55),
        (23, 39),
        (7, 59),
        (27, 43),
        (11, 51),
        (19, 35),
        (3, 61),
        (29, 45),
        (13, 53),
        (21, 37),
        (5, 57),
        (25, 41),
        (9, 49),
        (17, 33),
    ],
}


def _ibjjf_display_order(first_round, play_in_count=0):
    """Return first-round rows in IBJJF's visual bracket order.

    The seed layout tables are stored in a canonical tree order: seed 1's half
    first, then seed 2's half. IBJJF's rendered brackets put seed 2's half on
    top and seed 1's half underneath for 8- and 16-slot brackets. The 32-slot
    bracket follows a 4-row page rhythm. The 64-slot bracket follows an 8-row
    page rhythm. All transforms move only complete first-round sibling rows,
    so tree geometry is unchanged.
    """
    count = len(first_round)
    if count == 4:
        return [
            (min(a, b), max(a, b)) if b is not None else (a, None)
            for a, b in reversed(first_round)
        ]

    if count == 32:
        if play_in_count == 23:
            ordered = []
            for start in range(0, count, 8):
                block = first_round[start : start + 8]
                if start == 24:
                    ordered.extend(
                        [
                            block[2],
                            block[3],
                            block[1],
                            block[0],
                            block[5],
                            block[4],
                            block[7],
                            block[6],
                        ]
                    )
                else:
                    ordered.extend(
                        [
                            block[2],
                            block[3],
                            block[1],
                            block[0],
                            block[6],
                            block[7],
                            block[5],
                            block[4],
                        ]
                    )
            return ordered

        if play_in_count == 20:
            ordered = []
            for start in range(0, count, 8):
                block = first_round[start : start + 8]
                ordered.extend(
                    [
                        block[2],
                        block[3],
                        block[1],
                        block[0],
                        block[5],
                        block[4],
                        block[7],
                        block[6],
                    ]
                )
            return ordered

        if play_in_count == 12:
            ordered = []
            for start in range(0, count, 8):
                first = first_round[start : start + 4]
                second = first_round[start + 4 : start + 8]
                ordered.extend([second[1], second[0], second[3], second[2]])
                ordered.extend([first[1], first[0], first[2], first[3]])
            return ordered

        if play_in_count >= 8:
            ordered = []
            for start in range(0, count, 4):
                block = first_round[start : start + 4]
                ordered.extend([block[1], block[0], block[2], block[3]])
            return ordered

        quarter_orders = {
            1: (3, 2, 0, 1),
            3: (2, 3, 1, 0),
            4: (0, 1, 2, 3),
        }
        quarters_to_swap = {
            1: {3},
            3: {1, 2, 3},
            4: {0, 1, 2, 3},
        }
        quarter_order = quarter_orders.get(play_in_count, (2, 3, 1, 0))
        swap_quarters = quarters_to_swap.get(play_in_count, {1, 2, 3})
        ordered = []
        quarter_size = count // 4
        for quarter in quarter_order:
            start = quarter * quarter_size
            block = first_round[start : start + quarter_size]
            if quarter in swap_quarters:
                ordered.extend([block[1], block[0], *block[2:]])
            else:
                ordered.extend(block)
        return ordered

    if count == 64 and play_in_count == 8:
        ordered = []
        for start in range(0, count, 8):
            block = first_round[start : start + 8]
            ordered.extend([block[1], block[0], *block[2:]])
        return ordered

    if count == 64 and play_in_count == 2:
        ordered = []
        block_size = 8
        for block_index in (3, 2, 0, 1, 7, 6, 4, 5):
            start = block_index * block_size
            block = first_round[start : start + block_size]
            if block_index in {3, 7}:
                ordered.extend([block[1], block[0], *block[2:]])
            else:
                ordered.extend(block)
        return ordered

    if count >= 16 and count % 4 == 0:
        ordered = []
        for start in range(0, count, 4):
            block = first_round[start : start + 4]
            ordered.extend([block[1], block[0], block[2], block[3]])
        return ordered

    if count < 8 or count % 4 != 0:
        return first_round

    quadrant_size = count // 4
    ordered = []
    for start in (3 * quadrant_size, 2 * quadrant_size, 0, quadrant_size):
        ordered.extend(reversed(first_round[start : start + quadrant_size]))
    return ordered


def _bracket_slots(n):
    """Return ``(first_round, bracket_size)`` for an n-person IBJJF bracket.

    ``first_round`` is an ordered list of ``(red_seed, blue_seed)`` pairs
    covering every first-round slot in IBJJF's visual display order, where
    ``None`` denotes a bye.  ``bracket_size`` is the theoretical full bracket
    size (always a power of 2).

    Returns ``(None, None)`` when n < 4 or the bracket is larger than the
    layout tables cover.

    This is the single source of truth for estimated bracket layout; the
    frontend consumes these slots when constructing estimated matches.
    """
    if n < 4:
        return None, None

    effective_size = 1
    while effective_size * 2 <= n:
        effective_size *= 2

    play_in_count = n - effective_size
    bracket_size = effective_size * 2 if play_in_count > 0 else effective_size
    use_power_up_layout = effective_size >= 4 and play_in_count == effective_size - 1

    effective_layout = _IBJJF_SEED_LAYOUTS.get(effective_size)
    if effective_layout is None:
        return None, None

    play_in_pairs = {}
    if play_in_count > 0 and not use_power_up_layout:
        normalized = sorted(
            [(min(a, b), max(a, b)) for a, b in effective_layout],
            key=lambda p: p[0],
        )
        group_a = [p[1] for p in normalized]
        group_b = list(reversed([p[0] for p in normalized]))

        count_a = min(play_in_count, len(group_a))
        count_b = max(0, play_in_count - len(group_a))
        if effective_size == 32 and play_in_count == 12:
            selected_a = [17, 18, 19, 20, 29, 30, 31, 32, 25, 26, 27, 28]
        elif effective_size == 32 and play_in_count <= 4:
            selected_a = [29, 30, 31, 32][:count_a]
        elif effective_size == 64 and play_in_count == 8:
            selected_a = [57, 58, 59, 60, 61, 62, 63, 64]
        elif effective_size == 64 and play_in_count == 2:
            selected_a = [57, 58]
        else:
            selected_a = sorted(group_a[:count_a])
        if effective_size == 32 and play_in_count == 23:
            selected_b = [13, 10, 11, 12, 15, 14, 16]
        else:
            selected_b = sorted(group_b[:count_b])

        if effective_size <= 4:
            for i, s in enumerate(selected_a):
                play_in_pairs[s] = effective_size + len(selected_a) - i
            for i, s in enumerate(selected_b):
                play_in_pairs[s] = effective_size + len(selected_a) + 1 + i
        else:
            for i, s in enumerate(selected_a):
                play_in_pairs[s] = effective_size + 1 + i
            for i, s in enumerate(selected_b):
                play_in_pairs[s] = effective_size + len(selected_a) + 1 + i

    first_round = []
    if play_in_count == 0:
        first_round = list(effective_layout)
    elif use_power_up_layout:
        full_layout = _IBJJF_SEED_LAYOUTS.get(bracket_size)
        if full_layout is None:
            return None, None
        for a, b in full_layout:
            if a > n:
                first_round.append((b, None))
            elif b > n:
                first_round.append((a, None))
            else:
                first_round.append((a, b))
    else:
        for a, b in effective_layout:
            first_round.append(
                (a, play_in_pairs[a]) if a in play_in_pairs else (a, None)
            )
            first_round.append(
                (b, play_in_pairs[b]) if b in play_in_pairs else (b, None)
            )

    return _ibjjf_display_order(first_round, play_in_count), bracket_size


def _side(seed, n):
    """Which side (0 = seed 1's half, 1 = seed 2's half) a given seed lands on
    in an n-person IBJJF bracket.  Uses the actual layout from
    :func:`_bracket_slots`; falls back to seed-parity for oversized brackets.
    """
    first_round, _ = _bracket_slots(n)
    if first_round is None:
        if seed == 1:
            return 0
        if seed == 2:
            return 1
        return 0 if seed % 2 == 0 else 1

    half = len(first_round) // 2
    seed1_half = None
    seed2_half = None
    target_half = None

    for i, (a, b) in enumerate(first_round):
        row_half = 0 if i < half else 1
        if a == 1 or b == 1:
            seed1_half = row_half
        if a == 2 or b == 2:
            seed2_half = row_half
        if a == seed or (b is not None and b == seed):
            target_half = row_half

    if target_half is not None:
        if seed1_half is not None and target_half == seed1_half:
            return 0
        if seed2_half is not None and target_half == seed2_half:
            return 1
        return target_half

    if seed == 1:
        return 0
    if seed == 2:
        return 1
    return 0 if seed % 2 == 0 else 1


def add_side_swaps(rows):
    """Identify same-team side-swaps without mutating ``est_seed``.

    Assumes :func:`add_estimated_seeds` has already populated ``est_seed``
    contiguously (1..len(rows)) on every row. The natural (pre-swap)
    seeding is preserved on the rows; only the list of athletes that
    *would* be swapped is returned, so callers can flag those positions
    as uncertain.

    Bracket geometry: IBJJF brackets split by actual layout position (see
    :func:`_side`). The search walks all offsets from s2, skipping candidates
    that land on the same side as s2, until it finds a usable target.

    Pairs are processed in order of the worse-seeded (second) teammate,
    ascending — i.e. the pair whose s2 appears first when walking down
    the list is handled first. A later pair's swap may resolve an
    earlier pair as a side effect.

    Target selection mirrors observed IBJJF behavior: for each
    same-side pair with worse seed ``s2``, walk upward (s2+1, s2+2, ...)
    then downward (s2-1, s2-2, ...) skipping same-side seeds, and pick the
    first candidate that satisfies all of:

      - in bounds and not the teammate ``s1``;
      - the athlete at that seed is not already in a previously-emitted
        swap — IBJJF swaps are disjoint pairs, never chains;
      - the swap wouldn't pull another team's currently-OK pair into a
        new same-side collision.

    If no candidate satisfies the third rule, a second pass relaxes it
    (allowing a break as a last resort) while still respecting the
    disjoint-pairs constraint.

    Behavior:
      - len(rows) <= 3: do nothing.
      - Any team with > 2 athletes: bail out (no swaps) and return the
        offending team name(s) so callers can flag them.
      - For each same-team same-side pair: pick a target with the rules
        above and swap. If the worse-seeded teammate was already pulled
        into a prior swap, the pair is left as-is — we never chain a
        swap through a single athlete. Track the intended swap so later
        pairs see the post-swap geometry; the row ``est_seed`` values
        are restored before returning.

    Returns ``{"swaps": [{"name_a", "name_b"}, ...],
    "bailout_teams": list[str]}``.
    """
    swaps = []
    num = len(rows)
    if num <= 3:
        return {"swaps": swaps, "bailout_teams": []}

    teams = {}
    for r in rows:
        team = r.get("team")
        if not team:
            continue
        teams.setdefault(team, []).append(r)

    bailout_teams = [name for name, members in teams.items() if len(members) > 2]
    if bailout_teams:
        return {"swaps": [], "bailout_teams": bailout_teams}

    original_seeds = {id(r): r.get("est_seed") for r in rows}

    seed_to_row = {}
    for r in rows:
        s = r.get("est_seed")
        if s is not None:
            seed_to_row[s] = r

    # Process pairs in order of the worse-seeded (second) teammate, walking
    # down the list. A later pair's swap may resolve an earlier pair as a
    # side effect.
    pairs = sorted(
        [m for m in teams.values() if len(m) == 2],
        key=lambda m: max(x["est_seed"] for x in m),
    )

    swapped_ids = set()

    def would_break(candidate_seed, dest_side):
        # True iff the swap would pull the candidate's team into a
        # same-side collision they didn't have before. The candidate
        # ends up on ``dest_side`` after the swap; if their other
        # teammate is currently there, they'd land on the same side.
        row = seed_to_row[candidate_seed]
        team_name = row.get("team")
        if not team_name:
            return False
        members = teams.get(team_name, [])
        if len(members) != 2:
            return False
        other_row = members[0] if members[1] is row else members[1]
        other_side = _side(other_row["est_seed"], num)
        was_same_side = other_side == _side(row["est_seed"], num)
        will_be_same_side = other_side == dest_side
        return not was_same_side and will_be_same_side

    def find_target(s1, s2, dest_side):
        # Walk all offsets from s2, skipping candidates on the same side.
        # First pass refuses targets that would break another pair; second
        # pass relaxes that as a last resort. Both passes always refuse
        # already-swapped athletes (IBJJF swaps are disjoint pairs).
        opposite_side = 1 - dest_side
        for allow_break in (False, True):
            for direction in (1, -1):
                for offset in range(1, num):
                    c = s2 + direction * offset
                    if not (1 <= c <= num) or c == s1:
                        continue
                    if _side(c, num) != opposite_side:
                        continue
                    if id(seed_to_row[c]) in swapped_ids:
                        continue
                    if not allow_break and would_break(c, dest_side):
                        continue
                    return c
        return None

    for members in pairs:
        m1, m2 = sorted(members, key=lambda x: x["est_seed"])
        s1, s2 = m1["est_seed"], m2["est_seed"]
        if _side(s1, num) != _side(s2, num):
            continue
        if id(m2) in swapped_ids:
            # m2 was already moved by a prior swap; we don't chain a
            # second swap through the same athlete, so leave the pair
            # in its current (possibly still same-side) state.
            continue

        dest_side = _side(s2, num)
        target_seed = find_target(s1, s2, dest_side)
        if target_seed is None:
            continue

        other = seed_to_row[target_seed]
        # Mutate transiently so cascading pairs see the post-swap geometry,
        # then restore below.
        m2["est_seed"] = target_seed
        other["est_seed"] = s2
        seed_to_row[target_seed] = m2
        seed_to_row[s2] = other
        swaps.append({"name_a": m2["name"], "name_b": other["name"]})
        swapped_ids.add(id(m2))
        swapped_ids.add(id(other))

    for r in rows:
        r["est_seed"] = original_seeds[id(r)]

    return {"swaps": swaps, "bailout_teams": []}
