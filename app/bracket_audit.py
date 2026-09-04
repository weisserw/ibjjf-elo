"""Pure parsers and comparators for live bracket seeding audits.

The functions in this module deliberately do not depend on Flask or the
database.  They are shared by the admin audit worker, the live bracket route,
and the command-line bracket inspection helper.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import re
import unicodedata

from bs4 import BeautifulSoup

from normalize import normalize
from seeding import _bracket_slots


SEED_RE = re.compile(r"^\s*(\d+)\b")


def _soup(value):
    return (
        value
        if isinstance(value, BeautifulSoup)
        else BeautifulSoup(value, "html.parser")
    )


def _header_key(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("º", "o")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


HEADER_FIELDS = {
    "no competitor": "identity",
    "no competidor": "identity",
    "team": "team",
    "academia": "team",
    "grand slam pts": "grand_slam_points",
    "grand slam overall pts": "grand_slam_points",
    "pts grand slam": "grand_slam_points",
    "overall pts": "points",
    "overall pts without open class": "points",
    "pts geral": "points",
    "grand slam open class pts": "grand_slam_open_class_points",
    "overall open class pts": "open_class_points",
    "world champion last 3 editions": "world_champion_recent_years",
    "camp mundial ult 3 edicoes": "world_champion_recent_years",
    "last world title": "last_world_title_year",
    "world champ last edition": "world_champion_last_edition",
    "world champ four years ago": "world_champion_4_years_ago",
    "camp mundial 4 edicoes atras": "world_champion_4_years_ago",
    "world champ five years ago": "world_champion_5_years_ago",
    "camp mundial 5 edicoes atras": "world_champion_5_years_ago",
    "last brown belt world champion": "previous_brown_world_champion",
    "camp mundial faixa marrom": "previous_brown_world_champion",
    "former world champ": "former_world_champion",
    "camp mundial": "former_world_champion",
    "adult world champ": "adult_world_champion",
    "camp adulto": "adult_world_champion",
}


VARIANT_FIELDS = {
    "regular_weight": ("grand_slam_points", "points"),
    "regular_open": (
        "grand_slam_open_class_points",
        "grand_slam_points",
        "open_class_points",
        "points",
    ),
    "adult_black_weight": (
        "world_champion_recent",
        "last_world_title_year",
        "grand_slam_points",
        "world_champion_4_years_ago",
        "world_champion_5_years_ago",
        "previous_brown_world_champion",
        "former_world_champion",
        "points",
    ),
    "adult_black_open": (
        "world_champion_recent",
        "last_world_title_year",
        "grand_slam_open_class_points",
        "grand_slam_points",
        "world_champion_4_years_ago",
        "world_champion_5_years_ago",
        "previous_brown_world_champion",
        "former_world_champion",
        "open_class_points",
        "points",
    ),
}


def _master_field(header_key):
    aliases = (
        re.fullmatch(r"m\s*(\d+) world champ", header_key),
        re.fullmatch(r"camp mundial m\s*(\d+)", header_key),
    )
    match = next((item for item in aliases if item), None)
    return f"master_{match.group(1)}_world_champion" if match else None


def _variant(field_names):
    fields = set(field_names)
    is_open = "open_class_points" in fields or "grand_slam_open_class_points" in fields
    if "world_champion_recent_years" in fields:
        return "adult_black_open" if is_open else "adult_black_weight"
    if "adult_world_champion" in fields or any(
        field.startswith("master_") for field in fields
    ):
        return "master_black_open" if is_open else "master_black_weight"
    return "regular_open" if is_open else "regular_weight"


def criterion_fields(variant, official_fields=()):
    if variant.startswith("master_black"):
        master = sorted(
            (field for field in official_fields if field.startswith("master_")),
            key=lambda field: int(field.split("_")[1]),
        )
        suffix = (
            [
                "grand_slam_open_class_points",
                "grand_slam_points",
                "open_class_points",
                "points",
            ]
            if variant.endswith("open")
            else ["grand_slam_points", "points"]
        )
        return tuple(["adult_world_champion", *master, *suffix])
    return VARIANT_FIELDS[variant]


def _parse_flag(value):
    key = value.strip().casefold()
    if key in {"yes", "sim"}:
        return True
    if key in {"no", "nao", "não", "-", ""}:
        return False
    raise ValueError(f"Expected Yes/No flag, got {value!r}")


def _parse_optional_year(value):
    value = value.strip()
    if value in {"", "-", "No", "Não"}:
        return None
    if re.fullmatch(r"\d{4}", value):
        return int(value)
    raise ValueError(f"Expected a year or '-', got {value!r}")


def _parse_recent_years(value):
    value = value.strip()
    if value in {"", "-"}:
        return []
    years = [part.strip() for part in value.split(",")]
    if not years or any(not re.fullmatch(r"\d{4}", year) for year in years):
        raise ValueError(f"Expected comma-separated years or '-', got {value!r}")
    return [int(year) for year in years]


def _typed_cell(field, raw):
    if field in {
        "grand_slam_points",
        "points",
        "grand_slam_open_class_points",
        "open_class_points",
    }:
        return int(raw.strip())
    if field == "world_champion_recent_years":
        return _parse_recent_years(raw)
    if field in {"last_world_title_year", "former_world_champion"}:
        return _parse_optional_year(raw)
    if field in {
        "world_champion_last_edition",
        "world_champion_4_years_ago",
        "world_champion_5_years_ago",
        "previous_brown_world_champion",
        "adult_world_champion",
    } or field.startswith("master_"):
        return _parse_flag(raw)
    return raw.strip()


def parse_official_ranking(value):
    """Parse an official ranking table into raw and typed criterion values."""
    soup = _soup(value)
    table = soup.select_one("div.tournament-category__ranking > table.table")
    if table is None:
        return {
            "status": "absent",
            "variant": None,
            "headers": [],
            "unmapped_headers": [],
            "not_officially_exposed": [],
            "official_competitor_count": 0,
            "rows": [],
            "errors": [],
        }

    headers = [cell.get_text(" ", strip=True) for cell in table.select("thead th")]
    mapped = []
    unmapped = []
    for header in headers:
        key = _header_key(header)
        field = HEADER_FIELDS.get(key) or _master_field(key)
        mapped.append(field)
        if field is None:
            unmapped.append(header)

    variant = _variant(field for field in mapped if field)
    result = {
        "status": "unsupported" if unmapped else "parsed",
        "variant": variant,
        "headers": headers,
        "normalized_headers": [_header_key(header) for header in headers],
        "unmapped_headers": unmapped,
        "not_officially_exposed": [],
        "official_competitor_count": len(table.select("tbody tr")),
        "rows": [],
        "errors": [],
    }
    if unmapped:
        return result
    if not mapped or mapped[0] != "identity" or "team" not in mapped:
        result["status"] = "unsupported"
        result["errors"].append("Ranking table must contain identity and team columns")
        return result

    required = set(criterion_fields(variant, mapped))
    if "world_champion_recent" in required:
        required.remove("world_champion_recent")
        required.add("world_champion_recent_years")
    # These values are intentionally not exposed by the adult-black open table.
    if variant == "adult_black_open":
        required -= {"last_world_title_year", "former_world_champion"}
        required.add("world_champion_last_edition")
    exposed = set(mapped)
    if "world_champion_recent_years" in exposed:
        exposed.add("world_champion_recent")
    result["not_officially_exposed"] = sorted(
        set(criterion_fields(variant, mapped)) - exposed
    )
    missing = sorted(required - set(mapped))
    if missing:
        result["status"] = "unsupported"
        result["errors"].append(f"Missing required columns: {', '.join(missing)}")
        return result

    for row_number, tr in enumerate(table.select("tbody tr"), start=1):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) != len(mapped):
            result["errors"].append(
                f"Row {row_number}: expected {len(mapped)} cells, got {len(cells)}"
            )
            continue
        identity = cells[0]
        rank_node = identity.select_one(".prioriry-number, .priority-number")
        name_node = identity.select_one(".competitor-name")
        try:
            rank = int(rank_node.get_text(strip=True)) if rank_node else row_number
            name = name_node.get_text(" ", strip=True) if name_node else ""
            if not name:
                text = identity.get_text(" ", strip=True)
                name = re.sub(r"^\s*\d+\s*", "", text)
            raw_values = {}
            typed = {}
            team = ""
            for field, cell in zip(mapped[1:], cells[1:]):
                raw = cell.get_text(" ", strip=True)
                if field == "team":
                    team = raw
                    continue
                raw_values[field] = raw
                typed[field] = _typed_cell(field, raw)
            recent = typed.get("world_champion_recent_years")
            if recent is not None:
                typed["world_champion_recent"] = bool(recent)
                if "last_world_title_year" not in typed:
                    typed["last_world_title_year"] = max(recent) if recent else None
            result["rows"].append(
                {
                    "official_rank": rank,
                    "name": name,
                    "team": team,
                    "raw_criteria": raw_values,
                    "criteria": typed,
                    "errors": [],
                }
            )
        except (TypeError, ValueError) as exc:
            result["errors"].append(f"Row {row_number}: {exc}")

    if result["errors"]:
        result["status"] = "parse_error"
    return result


def parse_team_swaps(value):
    soup = _soup(value)
    swaps = []
    for swap_list in soup.select("ul.tournament-category__swap"):
        for item in swap_list.find_all("li", recursive=False):
            seeds = []
            for span in item.find_all("span"):
                match = SEED_RE.match(span.get_text(strip=True))
                if match:
                    seeds.append(int(match.group(1)))
            if len(seeds) >= 2:
                swaps.append((seeds[0], seeds[1]))
    return swaps


def composed_seed_swap_mapping(swaps, seeds=None):
    """Map displayed official seeds back to their original geometric slots."""
    seed_set = set(seeds or ())
    for left, right in swaps:
        seed_set.update((left, right))
    positions = {seed: seed for seed in seed_set}
    for left, right in swaps:
        positions.setdefault(left, left)
        positions.setdefault(right, right)
        positions[left], positions[right] = positions[right], positions[left]
    return positions


def parse_bracket_competitors(value):
    soup = _soup(value)
    by_seed = {}
    for node in soup.select("div.match-card__competitor"):
        if node.select_one(".match-card__bye"):
            continue
        seed_node = node.select_one(".match-card__competitor-n")
        if seed_node is None or not seed_node.get_text(strip=True).isdigit():
            continue
        seed = int(seed_node.get_text(strip=True))
        athlete_id = node.get("id") or ""
        athlete_id = athlete_id.rsplit("-", 1)[-1] if athlete_id else None
        name_node = node.select_one(".match-card__competitor-name")
        team_node = node.select_one(".match-card__club-name")
        candidate = {
            "seed": seed,
            "ibjjf_id": athlete_id,
            "name": name_node.get_text(" ", strip=True) if name_node else "",
            "team": team_node.get_text(" ", strip=True) if team_node else "",
        }
        current = by_seed.get(seed)
        if current is None or (not current["name"] and candidate["name"]):
            by_seed[seed] = candidate
    return [by_seed[seed] for seed in sorted(by_seed)]


def _is_power_of_two(value):
    return value > 0 and value & (value - 1) == 0


def first_round_slots_from_matches(matches, swaps=()):
    """Build audit geometry from normalized live ``parse_match`` records."""
    matches = sorted(matches, key=lambda match: match.get("match_num", 0))
    bracket_size = len(matches) + 1
    if not _is_power_of_two(bracket_size):
        raise ValueError(
            f"Expected match count + 1 to be a power of two, got {bracket_size}"
        )
    actual_numbers = [match.get("match_num") for match in matches]
    expected_numbers = list(range(1, bracket_size))
    if actual_numbers != expected_numbers:
        raise ValueError(
            f"Expected match numbers 1 through {bracket_size - 1}, got {actual_numbers}"
        )

    displayed_slots = []
    for match in matches[: bracket_size // 2]:
        pair = []
        for side in ("red", "blue"):
            if match.get(f"{side}_bye"):
                pair.append(None)
                continue
            seed = match.get(f"{side}_seed")
            if not isinstance(seed, int) or isinstance(seed, bool) or seed < 1:
                raise ValueError(
                    f"Match {match['match_num']} {side} competitor is missing a "
                    "numeric seed"
                )
            pair.append(seed)
        displayed_slots.append(tuple(pair))
    displayed_seeds = {
        seed for pair in displayed_slots for seed in pair if seed is not None
    }
    swaps = list(swaps)
    mapping = composed_seed_swap_mapping(swaps, displayed_seeds)
    slots = [
        tuple(mapping.get(seed, seed) if seed is not None else None for seed in pair)
        for pair in displayed_slots
    ]
    return {
        "bracket_size": bracket_size,
        "displayed_slots": displayed_slots,
        "slots": slots,
        "swaps": swaps,
        "swap_mapping": mapping,
    }


def sort_layout_evidence_slots(rows):
    def seed_key(seed):
        return seed is None, seed if seed is not None else 0

    normalized = [tuple(sorted(tuple(pair), key=seed_key)) for pair in rows]
    return sorted(
        normalized,
        key=lambda pair: tuple(seed_key(seed) for seed in pair),
    )


def compare_layout(parsed, official_competitor_count=None):
    actual = [tuple(pair) for pair in parsed["slots"]]
    real = [seed for pair in actual for seed in pair if seed is not None]
    unique = set(real)
    competitor_count = official_competitor_count or len(unique)
    expected, theoretical_size = _bracket_slots(competitor_count)

    evidence = {
        "actual_slots": sort_layout_evidence_slots(actual),
        "displayed_slots": parsed.get("displayed_slots", actual),
        "expected_slots": sort_layout_evidence_slots(expected),
        "parsed_bracket_size": parsed["bracket_size"],
        "theoretical_bracket_size": theoretical_size,
        "competitor_count": competitor_count,
        "swaps": parsed.get("swaps", []),
        "swap_mapping": parsed.get("swap_mapping", {}),
    }
    expected_coverage = set(range(1, competitor_count + 1))
    if (
        Counter(real) != Counter(expected_coverage)
        or parsed["bracket_size"] != theoretical_size
    ):
        return {
            "status": "seed_coverage_mismatch",
            "reason": "Seed coverage or bracket size differs",
            **evidence,
        }

    def pairings(rows):
        return Counter(
            frozenset(pair)
            for pair in rows
            if pair[0] is not None and pair[1] is not None
        )

    if pairings(actual) != pairings(expected):
        return {
            "status": "pairing_mismatch",
            "reason": "Non-bye pairings differ",
            **evidence,
        }
    return {"status": "exact", "reason": None, **evidence}


def _identity_key(name, team):
    return normalize(name or ""), normalize(team or "")


def reconcile_competitors(official_rows, live_rows, predicted_rows):
    live_by_seed = {row["seed"]: row for row in live_rows}
    predicted_by_ibjjf = defaultdict(list)
    predicted_by_identity = defaultdict(list)
    for row in predicted_rows:
        if row.get("ibjjf_id") is not None:
            predicted_by_ibjjf[str(row["ibjjf_id"])].append(row)
        names = {row.get("name", ""), row.get("personal_name", "")}
        for name in names:
            if name:
                predicted_by_identity[_identity_key(name, row.get("team"))].append(row)

    reconciled = []
    matched_predicted = set()
    for official in official_rows:
        live = live_by_seed.get(official["official_rank"])
        record = {
            "official": official,
            "live": live,
            "predicted": None,
            "status": "unresolved",
            "reason": None,
        }
        if live is None:
            record.update(
                status="official_missing", reason="No bracket card for official seed"
            )
            reconciled.append(record)
            continue
        if _identity_key(official["name"], official["team"]) != _identity_key(
            live["name"], live["team"]
        ):
            record.update(
                status="unresolved",
                reason="Ranking row and displayed seed identity differ",
            )
            reconciled.append(record)
            continue

        candidates = []
        if live.get("ibjjf_id") is not None:
            candidates = predicted_by_ibjjf.get(str(live["ibjjf_id"]), [])
        if not candidates:
            candidates = predicted_by_identity.get(
                _identity_key(official["name"], official["team"]), []
            )
        unique_candidates = {id(item): item for item in candidates}
        if len(unique_candidates) == 1:
            predicted = next(iter(unique_candidates.values()))
            record.update(status="matched", predicted=predicted)
            matched_predicted.add(id(predicted))
        elif len(unique_candidates) > 1:
            record.update(
                status="ambiguous", reason="More than one registration row matches"
            )
            record["candidates"] = list(unique_candidates.values())
        else:
            record.update(
                status="registration_missing",
                reason="No registration prediction row matches",
            )
        reconciled.append(record)

    for predicted in predicted_rows:
        if id(predicted) not in matched_predicted:
            # Do not duplicate rows already reported as ambiguous candidates.
            if any(predicted in row.get("candidates", []) for row in reconciled):
                continue
            reconciled.append(
                {
                    "official": None,
                    "live": None,
                    "predicted": predicted,
                    "status": "official_missing",
                    "reason": "Registration row is absent from official ranking",
                }
            )
    return reconciled


def compare_criteria(reconciled, variant, official_fields=()):
    fields = criterion_fields(variant, official_fields)
    rows = []
    mismatch_count = 0
    differing_field_count = 0
    unresolved_count = 0
    tie_only = False
    identity_mismatch = False
    for item in reconciled:
        comparison = {
            **item,
            "differences": [],
            "rank_matches": None,
            "comparison_status": "unverifiable",
        }
        if item["status"] != "matched":
            unresolved_count += 1
            identity_mismatch = True
            rows.append(comparison)
            continue
        official = item["official"]
        predicted = item["predicted"]
        typed = official["criteria"]
        for field in fields:
            if field not in typed:
                continue
            expected = predicted.get(field)
            actual = typed[field]
            if actual != expected:
                comparison["differences"].append(
                    {"field": field, "official": actual, "predicted": expected}
                )
        comparison["rank_matches"] = official["official_rank"] == predicted.get(
            "est_seed"
        )
        if comparison["differences"]:
            comparison["comparison_status"] = "criteria_mismatch"
            mismatch_count += 1
            differing_field_count += len(comparison["differences"])
        elif not comparison["rank_matches"] and predicted.get("est_seed_tied"):
            comparison["comparison_status"] = "tie_order_only"
            tie_only = True
        elif not comparison["rank_matches"]:
            comparison["comparison_status"] = "criteria_mismatch"
            comparison["differences"].append(
                {
                    "field": "official_rank",
                    "official": official["official_rank"],
                    "predicted": predicted.get("est_seed"),
                }
            )
            mismatch_count += 1
            differing_field_count += 1
        else:
            comparison["comparison_status"] = "match"
        rows.append(comparison)

    if mismatch_count:
        status = "criteria_mismatch"
    elif identity_mismatch:
        status = "identity_mismatch"
    elif tie_only:
        status = "tie_order_only"
    else:
        status = "match"
    return {
        "status": status,
        "rows": rows,
        "matched_count": sum(row["status"] == "matched" for row in reconciled),
        "mismatched_count": mismatch_count,
        "unresolved_count": unresolved_count,
        "differing_field_count": differing_field_count,
    }
