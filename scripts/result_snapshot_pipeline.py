"""Pure comparison primitives for ongoing IBJJF result snapshots.

Names and teams are mutable source attributes. Event/division/place identify a
result slot; a slot is promoted automatically only when its old and new sides
can be paired without guessing.
"""

from collections import defaultdict
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
    """Diff one event, pairing a crowded slot only after unchanged rows cancel."""
    old_slots, new_slots = defaultdict(list), defaultdict(list)
    for row in previous:
        old_slots[slot_key(row)].append(row)
    for row in candidate:
        new_slots[slot_key(row)].append(row)

    changes = []
    for key in sorted(set(old_slots) | set(new_slots)):
        before, after = old_slots[key], new_slots[key]
        old_by_name, new_by_name = defaultdict(list), defaultdict(list)
        for row in before:
            old_by_name[_fold(row.get("athlete_name"))].append(row)
        for row in after:
            new_by_name[_fold(row.get("athlete_name"))].append(row)

        remaining_old, remaining_new = [], []
        for name in sorted(set(old_by_name) | set(new_by_name)):
            old_rows = old_by_name[name]
            new_rows = new_by_name[name]
            paired_count = min(len(old_rows), len(new_rows))
            for old, new in zip(old_rows[:paired_count], new_rows[:paired_count]):
                kind = (
                    "unchanged"
                    if _fold(old.get("team_name")) == _fold(new.get("team_name"))
                    else "team_changed"
                )
                changes.append(ResultChange(kind, key, old, new, True))
            remaining_old.extend(old_rows[paired_count:])
            remaining_new.extend(new_rows[paired_count:])

        if len(remaining_old) == len(remaining_new) == 1:
            changes.append(
                ResultChange("renamed", key, remaining_old[0], remaining_new[0], True)
            )
        elif not remaining_old:
            changes.extend(
                ResultChange("added", key, None, row, True) for row in remaining_new
            )
        elif not remaining_new:
            changes.extend(
                ResultChange("removed", key, row, None, True) for row in remaining_old
            )
        else:
            changes.append(
                ResultChange("uncertain", key, remaining_old, remaining_new, False)
            )
    return changes
