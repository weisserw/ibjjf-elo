#!/usr/bin/env python3
"""Export livestream OCR text events to a test fixture and review table."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from livestream_match_linking import _scan_from_id  # noqa: E402
from models import LivestreamFrameTextEvent  # noqa: E402


SCORE_FIELDS = (
    "top_points",
    "top_advantages",
    "top_penalties",
    "bottom_points",
    "bottom_advantages",
    "bottom_penalties",
)

EVENT_FIELDS = (
    "frame_second",
    *SCORE_FIELDS,
    "scoreboard_state",
    "timer_state",
    "timer_value",
    "top_athlete_name",
    "top_team_name",
    "bottom_athlete_name",
    "bottom_team_name",
    "profile_id",
    "score_engine",
    "name_engine",
    "confidence",
)


def _parse_second(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    parts = value.split(":")
    if not 2 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(
            f"expected seconds, m:ss, or h:mm:ss, got {value!r}"
        )
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected numeric time parts, got {value!r}"
        ) from exc
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def _format_second(value: int | None) -> str:
    if value is None:
        return "-"
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _event_score(event: dict) -> str:
    top = (
        event.get("top_points"),
        event.get("top_advantages"),
        event.get("top_penalties"),
    )
    bottom = (
        event.get("bottom_points"),
        event.get("bottom_advantages"),
        event.get("bottom_penalties"),
    )
    if all(value is None for value in (*top, *bottom)):
        return "-"
    return (
        "/".join("-" if value is None else str(value) for value in top)
        + " - "
        + "/".join("-" if value is None else str(value) for value in bottom)
    )


def _decode_evidence(value: str | None):
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _event_to_dict(row: LivestreamFrameTextEvent) -> dict:
    event = {field: getattr(row, field) for field in EVENT_FIELDS}
    event["id"] = str(row.id)
    event["match_id"] = str(row.match_id) if row.match_id else None
    event["evidence"] = _decode_evidence(row.evidence_json)
    return event


def _markdown_value(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text.replace("|", "\\|")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_review(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        f"# Livestream Text Event Export: {payload['source']['scan_id']}",
        "",
        f"- archive_id: `{payload['source']['archive_id']}`",
        f"- range: `{_format_second(payload['range']['start_second'])}`"
        f" to `{_format_second(payload['range']['end_second'])}`",
        f"- events: `{len(payload['events'])}`",
        "",
        "| time | timer | score | top | bottom | state | conf | match_id |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for event in payload["events"]:
        timer = " ".join(
            part
            for part in (event.get("timer_state"), event.get("timer_value"))
            if part
        )
        confidence = event.get("confidence")
        rows.append(
            "| "
            + " | ".join(
                [
                    _markdown_value(_format_second(event["frame_second"])),
                    _markdown_value(timer),
                    _markdown_value(_event_score(event)),
                    _markdown_value(event.get("top_athlete_name")),
                    _markdown_value(event.get("bottom_athlete_name")),
                    _markdown_value(event.get("scoreboard_state")),
                    _markdown_value("" if confidence is None else f"{confidence:.3f}"),
                    _markdown_value(event.get("match_id")),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def export_events(
    scan_or_archive_id: str, start_second: int | None, end_second: int | None
):
    scan = _scan_from_id(db.session, scan_or_archive_id)
    if not scan:
        raise SystemExit(f"text scan/archive not found: {scan_or_archive_id}")

    query = LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
    if start_second is not None:
        query = query.filter(LivestreamFrameTextEvent.frame_second >= start_second)
    if end_second is not None:
        query = query.filter(LivestreamFrameTextEvent.frame_second <= end_second)
    rows = query.order_by(LivestreamFrameTextEvent.frame_second).all()

    return {
        "source": {
            "scan_id": str(scan.id),
            "archive_id": str(scan.archive_id),
            "status": scan.status,
            "parser_profile": scan.parser_profile,
            "score_engine": scan.score_engine,
            "name_engine": scan.name_engine,
        },
        "range": {
            "start_second": start_second,
            "end_second": end_second,
        },
        "events": [_event_to_dict(row) for row in rows],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export LivestreamFrameTextEvent rows for regression fixtures."
    )
    parser.add_argument("scan_or_archive_id")
    parser.add_argument("--start", type=_parse_second, default=None)
    parser.add_argument("--end", type=_parse_second, default=None)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with app.app_context():
        payload = export_events(args.scan_or_archive_id, args.start, args.end)
    _write_json(args.out, payload)
    if args.review:
        _write_review(args.review, payload)
    print(
        f"exported {len(payload['events'])} events "
        f"from {_format_second(args.start)} to {_format_second(args.end)} "
        f"-> {args.out}"
    )
    if args.review:
        print(f"wrote review -> {args.review}")


if __name__ == "__main__":
    main()
