from fnmatch import fnmatchcase
from extensions import db
from models import TeamNameMapping


def load_team_name_mappings():
    rows = db.session.query(
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
