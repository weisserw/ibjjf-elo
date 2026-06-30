#!/usr/bin/env python3
"""Link OCR text-scan windows to matches and print per-window diagnostics."""

from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from livestream_match_linking import (  # noqa: E402
    LOOKAHEAD_MATCHES,
    MIN_NAME_SCORE,
    MIN_SCORE_MARGIN,
    TIME_MATCH_WINDOW_SECONDS,
    _candidate_time_delta,
    _choice_for_candidate,
    _scan_from_id,
    analyze_candidate_loading,
    analyze_text_scan_links,
    extract_match_windows,
    link_completed_text_scan,
    livestream_rows_for_archive,
    load_candidates_for_archive,
)
from models import LivestreamFrameArchive, LivestreamFrameTextEvent  # noqa: E402


def _format_second(value: int | None) -> str:
    if value is None:
        return "-"
    hours, remainder = divmod(value, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _show_value(value: int | None) -> str:
    return "-" if value is None else str(value)


def _format_score(score: dict[str, int | None]) -> str:
    top = (
        score.get("top_points"),
        score.get("top_advantages"),
        score.get("top_penalties"),
    )
    bottom = (
        score.get("bottom_points"),
        score.get("bottom_advantages"),
        score.get("bottom_penalties"),
    )
    if all(value is None for value in (*top, *bottom)):
        return "-"
    top_text = "/".join(_show_value(value) for value in top)
    bottom_text = "/".join(_show_value(value) for value in bottom)
    return f"{top_text} - {bottom_text}"


def _print_decision(decision: dict, verbose: bool) -> None:
    names = " / ".join(decision["top_names"] + decision["bottom_names"]) or "-"
    video_offset = _format_second(decision["video_start_offset_seconds"])
    print(
        f"[{decision['window_index']}] "
        f"{_format_second(decision['start_second'])}-{_format_second(decision['end_second'])} "
        f"cursor={decision['cursor_before']} "
        f"video_offset={video_offset} "
        f"names={names!r} "
        f"score={_format_score(decision['final_score'])} "
        f"timer={_format_second(decision['final_timer_seconds'])} "
        f"running={decision.get('has_running_timer')}"
    )
    if decision["matched"]:
        match = decision["matched"]
        print(
            "  LINK "
            f"match={match['match_id']} "
            f"{match['winner']} def. {match['loser']} "
            f"video_offset={video_offset} "
            f"score={match['score']} raw={match['raw_name_score']} "
            f"expected={_format_second(match['expected_start_second'])} "
            f"stored_offset={_format_second(match['stored_video_start_offset_seconds'])} "
            f"delta={match['time_delta_seconds']}s"
        )
    else:
        print(f"  SKIP {decision['rejection_reason']}")

    if verbose:
        for candidate in decision["top_candidates"]:
            print(
                "    candidate "
                f"match={candidate['match_id']} "
                f"{candidate['winner']} def. {candidate['loser']} "
                f"score={candidate['score']} raw={candidate['raw_name_score']} "
                f"order={candidate['order_index']} "
                f"expected={_format_second(candidate['expected_start_second'])} "
                f"stored_offset={_format_second(candidate['stored_video_start_offset_seconds'])} "
                f"delta={candidate['time_delta_seconds']}s"
            )


def _candidate_gate(
    candidate, window, cursor: int, used_match_ids: set[uuid.UUID]
) -> str:
    if candidate.match.id in used_match_ids:
        return "used_match"
    gap = candidate.order_index - cursor
    time_delta = _candidate_time_delta(window, candidate)
    time_aligned = (
        time_delta is not None and abs(time_delta) <= TIME_MATCH_WINDOW_SECONDS
    )
    if candidate.order_index < cursor and not time_aligned:
        return "behind_cursor"
    if gap > LOOKAHEAD_MATCHES and not time_aligned:
        return "beyond_lookahead"
    return "eligible"


def _adjusted_candidate_score(candidate, window, cursor: int) -> float:
    choice = _choice_for_candidate(window, candidate)
    gap = candidate.order_index - cursor
    time_delta = _candidate_time_delta(window, candidate)
    time_aligned = (
        time_delta is not None and abs(time_delta) <= TIME_MATCH_WINDOW_SECONDS
    )
    if time_aligned:
        order_penalty = 0.0
        time_penalty = min(abs(time_delta) / 60.0 * 0.4, 12.0)
    else:
        order_penalty = min(gap * 3.0, 18.0)
        time_penalty = 0.0
    return choice.raw_score - order_penalty - time_penalty


def _candidate_participants(candidate) -> str:
    return " vs ".join(
        participant.athlete.name for participant in candidate.participants
    )


def _print_skipped_choice_debug(
    scan_or_archive_id,
    decisions: list[dict],
    limit: int,
    around_second: int | None,
) -> None:
    scan = _scan_from_id(db.session, scan_or_archive_id)
    if not scan:
        print("skip-choice-debug unavailable: text scan/archive not found")
        return
    archive = db.session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        print("skip-choice-debug unavailable: archive not found")
        return

    candidates = load_candidates_for_archive(db.session, archive)
    events = (
        LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    windows = {
        index: window
        for index, window in enumerate(extract_match_windows(events), start=1)
    }
    decisions_by_index = {decision["window_index"]: decision for decision in decisions}
    used_match_ids: set[uuid.UUID] = set()
    for index in sorted(decisions_by_index):
        decision = decisions_by_index[index]
        if decision["matched"]:
            used_match_ids.add(uuid.UUID(decision["matched"]["match_id"]))
            continue

        window = windows.get(index)
        if not window:
            continue
        if around_second is not None and not (
            decision["start_second"] <= around_second <= decision["end_second"]
            or abs(decision["start_second"] - around_second) <= 120
        ):
            continue

        cursor = decision["cursor_before"]
        scored = []
        for candidate in candidates:
            choice = _choice_for_candidate(window, candidate)
            time_delta = _candidate_time_delta(window, candidate)
            scored.append(
                {
                    "candidate": candidate,
                    "raw_score": choice.raw_score,
                    "adjusted_score": _adjusted_candidate_score(
                        candidate, window, cursor
                    ),
                    "time_delta": time_delta,
                    "gate": _candidate_gate(candidate, window, cursor, used_match_ids),
                }
            )
        scored.sort(key=lambda item: item["raw_score"], reverse=True)
        print(
            "  skip-choice-debug "
            f"window={index} reason={decision['rejection_reason']} "
            f"cursor={cursor} min_name_score={MIN_NAME_SCORE} "
            f"min_margin={MIN_SCORE_MARGIN} "
            f"loaded_candidates={len(candidates)}"
        )
        for item in scored[:limit]:
            candidate = item["candidate"]
            print(
                "    raw-candidate "
                f"gate={item['gate']} "
                f"match={candidate.match.id} "
                f"raw={item['raw_score']:.2f} "
                f"adjusted={item['adjusted_score']:.2f} "
                f"order={candidate.order_index} "
                f"gap={candidate.order_index - cursor} "
                f"expected={_format_second(candidate.expected_start_second)} "
                f"stored_offset={_format_second(candidate.match.video_start_offset_seconds)} "
                f"delta={item['time_delta']}s "
                f"time={candidate.match.happened_at.isoformat()} "
                f"location={candidate.match.match_location} "
                f"participants={_candidate_participants(candidate)}"
            )


def _print_candidate_coverage(scan_or_archive_id) -> None:
    scan = _scan_from_id(db.session, scan_or_archive_id)
    if not scan:
        print("candidate coverage unavailable: text scan/archive not found")
        return
    archive = db.session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        print("candidate coverage unavailable: archive not found")
        return
    candidates = load_candidates_for_archive(db.session, archive)
    print(f"candidate coverage count={len(candidates)}")
    for candidate in candidates:
        match = candidate.match
        names = " vs ".join(
            participant.athlete.name for participant in candidate.participants
        )
        print(
            "  candidate-coverage "
            f"order={candidate.order_index} match={match.id} "
            f"expected={_format_second(candidate.expected_start_second)} "
            f"stored_offset={_format_second(match.video_start_offset_seconds)} "
            f"time={match.happened_at.isoformat()} "
            f"location={match.match_location} participants={names}"
        )


def _print_candidate_load_debug(scan_or_archive_id, limit: int) -> None:
    report = analyze_candidate_loading(db.session, scan_or_archive_id)
    if report.skipped:
        print(f"candidate-load skipped={report.skipped}")
        return
    print(
        "candidate-load "
        f"youtube_video_id={report.youtube_video_id} "
        f"usages={report.usage_count} events={','.join(report.event_ids)} "
        f"total_matches={report.total_matches} included={report.included} "
        f"excluded={report.excluded} reason_counts={report.reason_counts}"
    )
    print(f"candidate-load reason_counts_by_event={report.reason_counts_by_event}")
    print(
        "candidate-load match_counts_by_event_day_mat="
        f"{report.match_counts_by_event_day_mat}"
    )
    print(
        "candidate-load included_counts_by_event_day_mat="
        f"{report.included_counts_by_event_day_mat}"
    )
    print(f"candidate-load stream_keys={report.stream_keys}")
    print(f"candidate-load event_start_dates={report.event_start_dates}")
    included_rows = [row for row in report.rows if row["included"]]
    excluded_rows = [row for row in report.rows if not row["included"]]
    print("candidate-load included:")
    for row in included_rows[:limit]:
        print(
            "  include "
            f"match={row['match_id']} expected={_format_second(row['expected_start_second'])} "
            f"stored_offset={_format_second(row['video_start_offset_seconds'])} "
            f"event_id={row['event_ibjjf_id']} "
            f"day={row['day_number']} mat={row['mat_number']} "
            f"time={row['happened_at']} location={row['match_location']} "
            f"fight={row['fight_number']} match_number={row['match_number']} "
            f"participants={row['participants']}"
        )
    if len(included_rows) > limit:
        print(f"  ... {len(included_rows) - limit} more included")
    print("candidate-load excluded:")
    for row in excluded_rows[:limit]:
        print(
            "  exclude "
            f"reason={row['reason']} match={row['match_id']} "
            f"event_id={row['event_ibjjf_id']} "
            f"day={row['day_number']} mat={row['mat_number']} "
            f"time={row['happened_at']} location={row['match_location']} "
            f"fight={row['fight_number']} match_number={row['match_number']} "
            f"participants={row['participants']}"
        )
    if len(excluded_rows) > limit:
        print(f"  ... {len(excluded_rows) - limit} more excluded")


def _print_livestream_rows(scan_or_archive_id) -> None:
    report = livestream_rows_for_archive(db.session, scan_or_archive_id)
    if report.skipped:
        print(f"livestream-rows skipped={report.skipped}")
        return
    print(
        "livestream-rows "
        f"youtube_video_id={report.youtube_video_id} count={len(report.rows)}"
    )
    for row in report.rows:
        print(
            "  livestream-row "
            f"id={row['id']} event_id={row['event_id']} "
            f"day={row['day_number']} mat={row['mat_number']} "
            f"start={row['start']} end={row['end']} "
            f"drift={row['drift_factor']} hide_all={row['hide_all']} "
            f"link={row['link']}"
        )


def _load_target_context(scan_or_archive_id, match_id):
    scan = _scan_from_id(db.session, scan_or_archive_id)
    if not scan:
        return None, None, None, []
    archive = db.session.get(LivestreamFrameArchive, scan.archive_id)
    if not archive:
        return scan, None, None, []
    candidates = load_candidates_for_archive(db.session, archive)
    target = next(
        (candidate for candidate in candidates if candidate.match.id == match_id),
        None,
    )
    events = (
        LivestreamFrameTextEvent.query.filter_by(scan_id=scan.id)
        .order_by(LivestreamFrameTextEvent.frame_second)
        .all()
    )
    return scan, archive, target, extract_match_windows(events)


def _print_target_summary(target) -> None:
    if not target:
        print("target match is not in the linker candidate set")
        return
    match = target.match
    names = " vs ".join(participant.athlete.name for participant in target.participants)
    print(
        "target "
        f"match={match.id} order={target.order_index} "
        f"expected={_format_second(target.expected_start_second)} "
        f"time={match.happened_at.isoformat()} location={match.match_location} "
        f"participants={names}"
    )


def _print_target_window_scores(decisions, windows, target, around_second) -> None:
    if not target:
        return
    decisions_by_index = {decision["window_index"]: decision for decision in decisions}
    for index, window in enumerate(windows, start=1):
        if around_second is not None and not (
            window.start_second <= around_second <= window.end_second
            or abs(window.start_second - around_second) <= 120
        ):
            continue
        decision = decisions_by_index.get(index)
        if not decision:
            continue
        choice = _choice_for_candidate(window, target)
        time_delta = _candidate_time_delta(window, target)
        behind_cursor = target.order_index < decision["cursor_before"]
        print(
            "  target-score "
            f"window={index} cursor={decision['cursor_before']} "
            f"behind_cursor={behind_cursor} "
            f"raw_name_score={choice.raw_score:.2f} "
            f"time_delta={time_delta}s "
            f"matched={bool(decision['matched'] and decision['matched']['match_id'] == str(target.match.id))}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Link OCR livestream text-scan windows to DB matches."
    )
    parser.add_argument("scan_or_archive_id", help="Text scan ID or archive ID")
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist links. Defaults to diagnostic dry-run only.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the top candidate matches for each OCR window.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit printed OCR windows.",
    )
    parser.add_argument(
        "--match-id",
        help="Print candidate and per-window scoring diagnostics for this match ID.",
    )
    parser.add_argument(
        "--around-second",
        type=int,
        help="Only print OCR windows near this stream second.",
    )
    parser.add_argument(
        "--candidate-coverage",
        action="store_true",
        help="Print every candidate loaded for this archive before window diagnostics.",
    )
    parser.add_argument(
        "--candidate-load-debug",
        action="store_true",
        help="Print candidate include/exclude diagnostics from DB match loading.",
    )
    parser.add_argument(
        "--livestream-rows",
        action="store_true",
        help="Print live_streams rows that share this archive's YouTube video ID.",
    )
    parser.add_argument(
        "--candidate-load-limit",
        type=int,
        default=100,
        help="Limit included/excluded rows printed by --candidate-load-debug.",
    )
    parser.add_argument(
        "--skip-choice-debug",
        action="store_true",
        help=(
            "For skipped windows, print top raw name-score candidates and why "
            "each is eligible, used, behind the cursor, or beyond lookahead."
        ),
    )
    parser.add_argument(
        "--skip-choice-limit",
        type=int,
        default=10,
        help="Limit raw-score candidates printed per skipped window.",
    )
    args = parser.parse_args()

    try:
        scan_or_archive_id = uuid.UUID(args.scan_or_archive_id)
    except ValueError as exc:
        raise SystemExit(f"Invalid UUID: {exc}") from exc
    match_id = None
    if args.match_id:
        try:
            match_id = uuid.UUID(args.match_id)
        except ValueError as exc:
            raise SystemExit(f"Invalid match UUID: {exc}") from exc

    with app.app_context():
        if args.candidate_coverage:
            _print_candidate_coverage(scan_or_archive_id)
        if args.livestream_rows:
            _print_livestream_rows(scan_or_archive_id)
        if args.candidate_load_debug:
            _print_candidate_load_debug(scan_or_archive_id, args.candidate_load_limit)
        analysis = analyze_text_scan_links(db.session, scan_or_archive_id)
        target = None
        windows = []
        if match_id:
            _scan, _archive, target, windows = _load_target_context(
                scan_or_archive_id, match_id
            )
            _print_target_summary(target)
        print(
            "analysis "
            f"linked={analysis.linked} windows={analysis.windows} "
            f"candidates={analysis.candidates} skipped={analysis.skipped}"
        )
        decisions = analysis.decisions
        if args.around_second is not None:
            decisions = [
                decision
                for decision in decisions
                if decision["start_second"]
                <= args.around_second
                <= decision["end_second"]
                or abs(decision["start_second"] - args.around_second) <= 120
            ]
        if args.limit is not None:
            decisions = decisions[: args.limit]
        for decision in decisions:
            _print_decision(decision, args.verbose)
        if args.skip_choice_debug:
            _print_skipped_choice_debug(
                scan_or_archive_id,
                analysis.decisions,
                args.skip_choice_limit,
                args.around_second,
            )
        if match_id:
            _print_target_window_scores(
                analysis.decisions,
                windows,
                target,
                args.around_second,
            )

        if args.commit:
            summary = link_completed_text_scan(db.session, scan_or_archive_id)
            db.session.commit()
            print(
                "committed "
                f"linked={summary.linked} windows={summary.windows} "
                f"candidates={summary.candidates} skipped={summary.skipped}"
            )
        else:
            db.session.rollback()
            print("dry-run only; pass --commit to persist links")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
