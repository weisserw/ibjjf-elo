"""Audit archived first-round pairings against the current bracket layouts.

Usage:
    python3 scripts/audit_archive_bracket_layouts.py bracket_layout_review.csv

The review CSV may use the hand-added ``url``/``swaps`` columns or the query's
``bracket_url``/``official_swaps`` columns. Swaps use ``N-M;N-M`` syntax.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from bracket_audit import composed_seed_swap_mapping  # noqa: E402
from seeding import _bracket_slots  # noqa: E402


SWAP_RE = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def parse_swaps(value: str) -> list[tuple[int, int]]:
    value = (value or "").strip()
    if not value or value.lower() == "none":
        return []
    swaps = []
    for item in value.split(";"):
        match = SWAP_RE.match(item)
        if not match:
            raise ValueError(f"Invalid swap {item!r}; expected N-M;N-M")
        swaps.append((int(match.group(1)), int(match.group(2))))
    return swaps


def normalized_pair(pair: tuple[int, int]) -> tuple[int, int]:
    return tuple(sorted(pair))


def audit_row(row: dict[str, str]) -> dict:
    competitor_count = int(row["competitor_count"])
    bracket_match_count = int(row["bracket_match_count"])
    seed_entries = json.loads(row["seed_entries"])
    swaps = parse_swaps(row.get("swaps") or row.get("official_swaps", ""))
    mapping = composed_seed_swap_mapping(swaps, range(1, competitor_count + 1))

    bracket_size = bracket_match_count + 1
    play_in_count = competitor_count - bracket_size // 2
    if play_in_count < 0:
        raise ValueError(
            f"N={competitor_count}: bracket capacity {bracket_size} is too small"
        )

    first_round_match_limit = bracket_size // 2
    by_match: dict[int, set[int]] = {}
    for entry in seed_entries:
        match_number = int(entry["first_match_number"])
        if match_number <= first_round_match_limit:
            by_match.setdefault(match_number, set()).add(int(entry["seed"]))

    malformed_matches = {
        number: sorted(seeds) for number, seeds in by_match.items() if len(seeds) != 2
    }
    if len(by_match) != play_in_count or malformed_matches:
        raise ValueError(
            f"N={competitor_count}: expected {play_in_count} play-ins in match "
            f"numbers 1..{first_round_match_limit}, found {len(by_match)}; "
            f"malformed matches {malformed_matches}"
        )

    displayed_pairs = [tuple(sorted(by_match[number])) for number in sorted(by_match)]
    official_pairs = [
        normalized_pair((mapping[left], mapping[right]))
        for left, right in displayed_pairs
    ]

    current_slots, current_bracket_size = _bracket_slots(competitor_count)
    if current_bracket_size != bracket_size:
        raise ValueError(
            f"N={competitor_count}: CSV bracket size is {bracket_size}, but current "
            f"code returns {current_bracket_size}"
        )
    current_pairs = [
        normalized_pair((left, right))
        for left, right in current_slots
        if left is not None and right is not None
    ]

    official_set = set(official_pairs)
    current_set = set(current_pairs)
    return {
        "competitor_count": competitor_count,
        "url": row.get("url") or row.get("bracket_url", ""),
        "swaps": swaps,
        "displayed_pairs": displayed_pairs,
        "official_pairs": official_pairs,
        "current_pairs": current_pairs,
        "current_slots": current_slots,
        "missing_from_current": sorted(official_set - current_set),
        "unexpected_in_current": sorted(current_set - official_set),
        "matches": official_set == current_set,
    }


def format_pair(pair: tuple[int | None, int | None]) -> str:
    return ",".join("bye" if seed is None else str(seed) for seed in pair)


def render_report(results: list[dict]) -> str:
    lines = []
    matching = sum(result["matches"] for result in results)
    lines.append(
        f"Summary: {matching}/{len(results)} layouts match; "
        f"{len(results) - matching} differ."
    )
    lines.append("")
    for result in results:
        status = "MATCH" if result["matches"] else "MISMATCH"
        lines.append(f"N={result['competitor_count']}: {status}")
        lines.append(f"URL: {result['url']}")
        lines.append(f"Swaps: {result['swaps'] or 'none'}")
        lines.append(
            "Official corrected play-ins: "
            + "; ".join(format_pair(pair) for pair in result["official_pairs"])
        )
        lines.append(
            "Current-code play-ins: "
            + "; ".join(format_pair(pair) for pair in result["current_pairs"])
        )
        if not result["matches"]:
            lines.append(
                "Missing from current: "
                + "; ".join(
                    format_pair(pair) for pair in result["missing_from_current"]
                )
            )
            lines.append(
                "Unexpected in current: "
                + "; ".join(
                    format_pair(pair) for pair in result["unexpected_in_current"]
                )
            )
        lines.append("Current full layout:")
        lines.extend(f"  {format_pair(pair)}" for pair in result["current_slots"])
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="Report path (default: CSV filename with .audit.txt suffix)",
    )
    args = parser.parse_args()
    output = args.output or args.csv_file.with_suffix(".audit.txt")

    with args.csv_file.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    results = [audit_row(row) for row in rows]
    output.write_text(render_report(results), encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
