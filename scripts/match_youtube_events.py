#!/usr/bin/env python3
"""Match youtube event names to canonical IBJJF event names."""

from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Domain-specific aliases and typo repair for this dataset.
PHRASE_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bno\s*[- ]?gi\b", re.I), " no gi "),
    (re.compile(r"\bsem\s+kimono\b", re.I), " no gi "),
    (re.compile(r"\bchampionsip\b", re.I), " championship "),
    (re.compile(r"\bjiu\s*[- ]?jisu\b", re.I), " jiu jitsu "),
    (re.compile(r"\beuropian\b", re.I), " european "),
    (re.compile(r"\bnew\s+yok\b", re.I), " new york "),
    (re.compile(r"\bsparing\b", re.I), " spring "),
    (re.compile(r"\bbasilia\b", re.I), " brasilia "),
    (re.compile(r"\bitajai\b", re.I), " itaji "),
    (re.compile(r"\babs\.?\s*gp\b", re.I), " absolute grand prix "),
    (re.compile(r"\babsolute\s+gp\b", re.I), " absolute grand prix "),
    (re.compile(r"\bbrasleiro\b", re.I), " campeonato brasileiro "),
    (re.compile(r"\bbrazilian\s+nationals\b", re.I), " campeonato brasileiro "),
    (re.compile(r"\bbrasileiro\b", re.I), " campeonato brasileiro "),
    (re.compile(r"\bsul\s*[- ]?americano\b", re.I), " campeonato sul americano "),
    (re.compile(r"\bsul\s*-?\s*brasileiro\b", re.I), " campeonato sul brasileiro "),
    (re.compile(r"\bla\b", re.I), " los angeles "),
    (re.compile(r"\boc\b", re.I), " orange county "),
    (re.compile(r"\bd\.?c\.?\b", re.I), " washington dc "),
]

GENERIC_TOKENS = {
    "ibjjf",
    "jiu",
    "jitsu",
    "international",
    "championship",
    "open",
    "de",
    "do",
    "da",
    "the",
    "and",
}

FAMILY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("absolute_gp", re.compile(r"\babsolute\s+grand\s+prix\b")),
    ("pan_pacific", re.compile(r"\bpan\s+pacific\b")),
    ("pan", re.compile(r"\bpan\b")),
    ("world_master", re.compile(r"\bworld\s+master\b")),
    ("world", re.compile(r"\bworld\b")),
    ("campeonato_sul_americano", re.compile(r"\bcampeonato\s+sul\s+americano\b")),
    ("campeonato_sul_brasileiro", re.compile(r"\bcampeonato\s+sul\s+brasileiro\b")),
    ("campeonato_brasileiro", re.compile(r"\bcampeonato\s+brasileiro\b")),
]


@dataclass(frozen=True)
class ParsedEvent:
    original: str
    normalized: str
    year: int | None
    is_no_gi: bool
    family: str | None
    core_tokens: tuple[str, ...]


@dataclass(frozen=True)
class MatchResult:
    youtube_event: str
    matched_event: str
    score: float
    score_gap: float
    status: str
    reason: str


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    value = strip_accents(text).lower()
    for pattern, replacement in PHRASE_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_event(name: str) -> ParsedEvent:
    normalized = normalize_text(name)
    year_match = YEAR_RE.search(normalized)
    year = int(year_match.group(1)) if year_match else None
    is_no_gi = bool(re.search(r"\bno\s+gi\b", normalized))

    family = None
    for family_name, pattern in FAMILY_PATTERNS:
        if pattern.search(normalized):
            family = family_name
            break

    core = YEAR_RE.sub(" ", normalized)
    core = re.sub(r"\bno\s+gi\b", " ", core)
    tokens = [token for token in core.split() if token not in GENERIC_TOKENS]
    core_tokens = tuple(tokens)

    return ParsedEvent(
        original=name,
        normalized=normalized,
        year=year,
        is_no_gi=is_no_gi,
        family=family,
        core_tokens=core_tokens,
    )


def token_set_similarity(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    if not a or not b:
        return 0.0
    set_a = set(a)
    set_b = set(b)
    intersection = len(set_a & set_b)
    if intersection == 0:
        return 0.0
    precision = intersection / len(set_a)
    recall = intersection / len(set_b)
    return (2 * precision * recall) / (precision + recall)


def sequence_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def pair_score(y: ParsedEvent, e: ParsedEvent) -> float:
    token_score = token_set_similarity(y.core_tokens, e.core_tokens)
    seq_score = sequence_similarity(" ".join(y.core_tokens), " ".join(e.core_tokens))

    score = (token_score * 70.0) + (seq_score * 20.0)

    if y.family and e.family:
        score += 10.0 if y.family == e.family else -18.0

    if y.year is not None and e.year is None:
        score -= 5.0

    if y.is_no_gi == e.is_no_gi:
        score += 8.0
    else:
        if y.family == "absolute_gp" and e.family == "absolute_gp":
            score -= 4.0
        else:
            score -= 25.0

    return max(0.0, min(100.0, score))


def choose_candidates(y: ParsedEvent, events: list[ParsedEvent]) -> list[ParsedEvent]:
    by_year = [
        event
        for event in events
        if y.year is None or event.year == y.year or event.year is None
    ]
    if by_year:
        if y.family == "absolute_gp":
            return by_year
        same_mode = [event for event in by_year if event.is_no_gi == y.is_no_gi]
        if same_mode:
            return same_mode
        return by_year

    same_mode = [event for event in events if event.is_no_gi == y.is_no_gi]
    if same_mode:
        return same_mode

    return events


def match_one(y: ParsedEvent, events: list[ParsedEvent]) -> MatchResult:
    if y.original.strip().lower() == "event_name":
        return MatchResult(y.original, "", 0.0, 0.0, "review", "looks_like_header")

    candidates = choose_candidates(y, events)
    scored = sorted(
        ((pair_score(y, event), event) for event in candidates),
        key=lambda item: item[0],
        reverse=True,
    )

    top_score, top_event = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    gap = top_score - second_score

    if top_score >= 98.0:
        status = "auto"
        reason = "very_high_score"
    elif top_score >= 90.0 and gap >= 8.0:
        status = "auto"
        reason = "high_score_clear_gap"
    elif top_score >= 84.0 and gap >= 12.0:
        status = "auto"
        reason = "good_score_large_gap"
    else:
        status = "review"
        if top_score < 84.0:
            reason = "low_score"
        else:
            reason = "small_gap"

    return MatchResult(
        youtube_event=y.original,
        matched_event=top_event.original,
        score=round(top_score, 2),
        score_gap=round(gap, 2),
        status=status,
        reason=reason,
    )


def read_events(path: Path) -> list[str]:
    rows: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            value = row[0].strip()
            if value:
                rows.append(value)
    return rows


def write_results(path: Path, rows: Iterable[MatchResult]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["youtube_event", "matched_event", "score", "score_gap", "status", "reason"]
        )
        for row in rows:
            writer.writerow(
                [
                    row.youtube_event,
                    row.matched_event,
                    f"{row.score:.2f}",
                    f"{row.score_gap:.2f}",
                    row.status,
                    row.reason,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Match youtube event names to canonical events"
    )
    parser.add_argument(
        "--youtube",
        default="youtube_events.csv",
        help="Path to youtube event names CSV",
    )
    parser.add_argument(
        "--events", default="events.csv", help="Path to canonical event names CSV"
    )
    parser.add_argument(
        "--out",
        default="youtube_event_matches.csv",
        help="Output CSV with best match per youtube event",
    )
    parser.add_argument(
        "--review-out",
        default="youtube_event_matches_review.csv",
        help="Output CSV with rows requiring review",
    )
    args = parser.parse_args()

    youtube_rows = read_events(Path(args.youtube))
    event_rows = read_events(Path(args.events))

    parsed_events = [parse_event(name) for name in event_rows]
    results = [
        match_one(parse_event(youtube_name), parsed_events)
        for youtube_name in youtube_rows
    ]

    write_results(Path(args.out), results)
    review_rows = [result for result in results if result.status != "auto"]
    write_results(Path(args.review_out), review_rows)

    auto_count = sum(result.status == "auto" for result in results)
    review_count = len(results) - auto_count
    print(f"Matched {len(results)} youtube rows against {len(parsed_events)} events")
    print(f"Auto matches: {auto_count}")
    print(f"Needs review: {review_count}")
    print(f"Wrote: {args.out}")
    print(f"Wrote: {args.review_out}")


if __name__ == "__main__":
    main()
