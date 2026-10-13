from fnmatch import fnmatchcase
from extensions import db
from models import Team, TeamNameMapping


def load_team_name_mappings(session=None):
    session = db.session if session is None else session
    rows = session.query(
        TeamNameMapping.name_match,
        TeamNameMapping.mapped_name,
    ).all()
    exact_mappings = {}
    glob_mappings = []

    for name_match, mapped_name in rows:
        if any(ch in name_match for ch in "*?["):
            glob_mappings.append((name_match, mapped_name))
            continue
        exact_mappings[name_match] = mapped_name

    # More specific glob patterns win if multiple patterns match.
    glob_mappings.sort(
        key=lambda item: len(
            item[0].replace("*", "").replace("?", "").replace("[", "").replace("]", "")
        ),
        reverse=True,
    )
    return exact_mappings, glob_mappings


def resolve_dupe_team_name(team_name, exact_mappings, glob_mappings):
    if team_name in exact_mappings:
        return exact_mappings[team_name]

    for pattern, mapped_name in glob_mappings:
        if fnmatchcase(team_name, pattern):
            return mapped_name

    return team_name


def load_canonical_team_names(session):
    """Build a run-local lookup with two queries, never one query per match."""
    exact_mappings, glob_mappings = load_team_name_mappings(session)
    resolved_names = {}
    teams = {}
    for team_id, name in session.query(Team.id, Team.name):
        if name not in resolved_names:
            resolved_names[name] = (
                resolve_dupe_team_name(name, exact_mappings, glob_mappings)
                if name
                else None
            )
        teams[team_id] = resolved_names[name]
    return teams


def same_canonical_team(red_team_id, blue_team_id, canonical_team_names=None):
    if red_team_id is None or blue_team_id is None:
        return False
    if red_team_id == blue_team_id:
        return True
    if canonical_team_names is None:
        return False
    red_name = canonical_team_names.get(red_team_id)
    return bool(red_name) and red_name == canonical_team_names.get(blue_team_id)
