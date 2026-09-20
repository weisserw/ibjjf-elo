"""Pure comparison primitives for ongoing IBJJF result snapshots.

Names and teams are mutable source attributes. Event/division/place identify a
result slot; a slot is promoted automatically only when its old and new sides
can be paired without guessing.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib


def _fold(value):
    return " ".join(str(value or "").casefold().split())


def event_key(row):
    source = _fold(row.get("source"))
    event_id = str(row.get("event_ibjjf_id") or "").strip()
    return (
        f"{source}:id:{event_id}"
        if event_id
        else f"{source}:name:{_fold(row.get('event_name'))}"
    )


def slot_key(row):
    return f"{event_key(row)}|{_fold(row.get('division'))}|{int(row['place'])}"


def occurrence_key(row):
    """Stable key only for an unambiguous single-winner result slot."""
    return hashlib.sha256(slot_key(row).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResultChange:
    change_type: str
    slot_key: str
    old: object = None
    new: object = None
    automatic: bool = False


def compare_event_rows(previous, candidate):
    """Diff one event while refusing to pair crowded/two-bronze slots."""
    old_slots, new_slots = defaultdict(list), defaultdict(list)
    for row in previous:
        old_slots[slot_key(row)].append(row)
    for row in candidate:
        new_slots[slot_key(row)].append(row)

    changes = []
    for key in sorted(set(old_slots) | set(new_slots)):
        before, after = old_slots[key], new_slots[key]
        old_names = Counter(_fold(r.get("athlete_name")) for r in before)
        new_names = Counter(_fold(r.get("athlete_name")) for r in after)
        if old_names == new_names:
            old_by_name = {_fold(r.get("athlete_name")): r for r in before}
            for row in after:
                old = old_by_name[_fold(row.get("athlete_name"))]
                kind = (
                    "unchanged"
                    if _fold(old.get("team_name")) == _fold(row.get("team_name"))
                    else "team_changed"
                )
                changes.append(ResultChange(kind, key, old, row, True))
            continue
        if len(before) == len(after) == 1:
            changes.append(ResultChange("renamed", key, before[0], after[0], True))
        elif not before:
            changes.extend(ResultChange("added", key, None, row, True) for row in after)
        elif not after:
            changes.extend(
                ResultChange("removed", key, row, None, True) for row in before
            )
        else:
            changes.append(ResultChange("uncertain", key, before, after, False))
    return changes
