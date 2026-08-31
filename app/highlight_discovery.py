from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, tuple_
from sqlalchemy.orm import selectinload

from constants import NON_ELITE_BELTS
from elo import (
    EloCompetitor,
    division_default_rating,
    elite_tier,
    rating_maturity,
    rating_top_percent,
)
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    AthleteRatingAverage,
    Division,
    Event,
    LivestreamFrameTextEvent,
    Match,
    MatchParticipant,
    Medal,
)
from normalize import normalize
from routes.matches import (
    DQ_TYPE_NOTES,
    build_match_detail_payload,
    match_detail_video_lead_seconds,
)


SCHEMA_VERSION = 3
MAX_RESULT_MOMENTS = 100
MAX_CANDIDATE_MATCHES = 500
EVENT_TYPES = {"all", "decision", "dq", "match_start", "submission", "score"}
SCORE_CATEGORIES = {"points", "advantages", "penalties"}
ALLOWED_ARGS = {
    "event_type",
    "days",
    "limit",
    "gi",
    "age",
    "belt",
    "event_name",
    "athlete_name",
    "athlete_id",
    "match_id",
    "gender",
    "score_category",
    "score_delta",
}
SCORE_FIELDS = ("points", "advantages", "penalties")


class HighlightDiscoveryQueryError(ValueError):
    pass


def _iso_datetime(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _int_arg(args, name, *, default=None, minimum=None, maximum=None):
    raw = args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise HighlightDiscoveryQueryError(f"{name} must be an integer") from exc
    if str(value) != str(raw).strip():
        raise HighlightDiscoveryQueryError(f"{name} must be an integer")
    if (
        minimum is not None
        and value < minimum
        or maximum is not None
        and value > maximum
    ):
        raise HighlightDiscoveryQueryError(
            f"{name} must be an integer between {minimum} and {maximum}"
        )
    return value


def _uuid_arg(args, name):
    raw = (args.get(name) or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise HighlightDiscoveryQueryError(f"{name} must be a UUID") from exc


def _parse_filters(args):
    unknown = sorted(set(args.keys()) - ALLOWED_ARGS)
    if unknown:
        raise HighlightDiscoveryQueryError(
            f"unknown query parameter(s): {', '.join(unknown)}"
        )

    event_type = (args.get("event_type") or "submission").strip().lower()
    if event_type not in EVENT_TYPES:
        raise HighlightDiscoveryQueryError(
            "event_type must be one of: all, decision, dq, match_start, submission, score"
        )
    days = _int_arg(args, "days", minimum=1, maximum=90)
    limit = _int_arg(
        args,
        "limit",
        default=30,
        minimum=1,
        maximum=MAX_RESULT_MOMENTS,
    )
    score_category = (args.get("score_category") or "").strip().lower() or None
    score_delta = _int_arg(args, "score_delta", minimum=1, maximum=99)
    if event_type != "score" and (
        score_category is not None or score_delta is not None
    ):
        raise HighlightDiscoveryQueryError(
            "score_category and score_delta are only valid for score events"
        )
    if score_category is not None and score_category not in SCORE_CATEGORIES:
        raise HighlightDiscoveryQueryError(
            "score_category must be one of: points, advantages, penalties"
        )

    gi_raw = (args.get("gi") or "true").strip().lower()
    if gi_raw not in {"all", "true", "false"}:
        raise HighlightDiscoveryQueryError("gi must be one of: all, true, false")
    gender = (args.get("gender") or "").strip().lower() or None
    if gender not in {None, "male", "female"}:
        raise HighlightDiscoveryQueryError("gender must be one of: male, female")

    return {
        "event_type": event_type,
        "days": days,
        "limit": limit,
        "gi": None if gi_raw == "all" else gi_raw == "true",
        "age": (args.get("age") or "").strip() or None,
        "belt": (args.get("belt") or "").strip() or None,
        "event_name": (args.get("event_name") or "").strip() or None,
        "athlete_name": (args.get("athlete_name") or "").strip() or None,
        "athlete_id": _uuid_arg(args, "athlete_id"),
        "match_id": _uuid_arg(args, "match_id"),
        "gender": gender,
        "score_category": score_category,
        "score_delta": score_delta,
    }


def _candidate_matches(filters):
    query = Match.query.options(
        selectinload(Match.event),
        selectinload(Match.division),
        selectinload(Match.participants).selectinload(MatchParticipant.athlete),
        selectinload(Match.participants).selectinload(MatchParticipant.team),
    ).filter(
        db.session.query(LivestreamFrameTextEvent.id)
        .filter(LivestreamFrameTextEvent.match_id == Match.id)
        .exists()
    )
    if filters["match_id"] is not None:
        query = query.filter(Match.id == filters["match_id"])
    if filters["event_type"] == "dq":
        dq_notes = (
            note for note_group in DQ_TYPE_NOTES.values() for note in note_group
        )
        query = query.filter(
            db.session.query(MatchParticipant.id)
            .filter(
                MatchParticipant.match_id == Match.id,
                or_(*(MatchParticipant.note.like(f"%{note}%") for note in dq_notes)),
            )
            .exists()
        )
    if filters["days"] is not None:
        query = query.filter(
            Match.happened_at >= datetime.utcnow() - timedelta(days=filters["days"])
        )
    if filters["event_name"]:
        event_name_tokens = normalize(filters["event_name"]).split()
        event_query = db.session.query(Event.id)
        for token in event_name_tokens:
            event_query = event_query.filter(Event.normalized_name.like(f"%{token}%"))
        query = query.filter(Match.event_id.in_(event_query))
    if filters["athlete_id"] is not None:
        query = query.filter(
            db.session.query(MatchParticipant.id)
            .filter(
                MatchParticipant.match_id == Match.id,
                MatchParticipant.athlete_id == filters["athlete_id"],
            )
            .exists()
        )
    if filters["athlete_name"]:
        query = query.filter(
            db.session.query(MatchParticipant.id)
            .join(Athlete, MatchParticipant.athlete_id == Athlete.id)
            .filter(
                MatchParticipant.match_id == Match.id,
                Athlete.normalized_name == normalize(filters["athlete_name"]),
            )
            .exists()
        )

    division_conditions = []
    if filters["gi"] is not None:
        division_conditions.append(Division.gi == filters["gi"])
    for field in ("age", "belt", "gender"):
        if filters[field]:
            division_conditions.append(getattr(Division, field).ilike(filters[field]))
    if division_conditions:
        query = query.filter(
            Match.division_id.in_(
                db.session.query(Division.id).filter(*division_conditions)
            )
        )
    candidate_limit = min(
        MAX_CANDIDATE_MATCHES,
        max(filters["limit"] * 5, filters["limit"]),
    )
    return (
        query.order_by(Match.happened_at.desc(), Match.id).limit(candidate_limit).all()
    )


def _bulk_context(matches):
    match_ids = [match.id for match in matches]
    raw_by_match = defaultdict(list)
    if match_ids:
        rows = (
            LivestreamFrameTextEvent.query.options(
                selectinload(LivestreamFrameTextEvent.archive)
            )
            .filter(LivestreamFrameTextEvent.match_id.in_(match_ids))
            .order_by(
                LivestreamFrameTextEvent.match_id,
                LivestreamFrameTextEvent.frame_second,
                LivestreamFrameTextEvent.id,
            )
            .all()
        )
        for row in rows:
            raw_by_match[row.match_id].append(row)

    athlete_ids = {
        participant.athlete_id
        for match in matches
        for participant in match.participants
    }
    rating_rows = (
        AthleteRating.query.filter(AthleteRating.athlete_id.in_(athlete_ids)).all()
        if athlete_ids
        else []
    )
    ratings = {
        (
            row.athlete_id,
            bool(row.gi),
            row.gender,
            row.age,
            row.belt,
            row.weight,
        ): row
        for row in rating_rows
    }

    categories = {
        (
            bool(match.division.gi),
            match.division.gender,
            match.division.age,
            match.division.belt,
            match.division.weight,
        )
        for match in matches
        if match.division is not None
    }
    average_conditions = [
        and_(
            AthleteRatingAverage.gi == gi,
            AthleteRatingAverage.gender == gender,
            AthleteRatingAverage.age == age,
            AthleteRatingAverage.belt == belt,
            AthleteRatingAverage.weight == weight,
        )
        for gi, gender, age, belt, weight in categories
    ]
    average_rows = (
        AthleteRatingAverage.query.filter(or_(*average_conditions)).all()
        if average_conditions
        else []
    )
    averages = {
        (bool(row.gi), row.gender, row.age, row.belt, row.weight): row.avg_rating
        for row in average_rows
    }

    medal_scopes = {(match.event_id, match.division_id) for match in matches}
    medal_rows = (
        Medal.query.filter(
            tuple_(Medal.event_id, Medal.division_id).in_(
                sorted(
                    medal_scopes,
                    key=lambda pair: (str(pair[0]), str(pair[1])),
                )
            ),
            Medal.athlete_id.in_(athlete_ids),
        ).all()
        if medal_scopes and athlete_ids
        else []
    )
    medal_places = {
        (row.event_id, row.division_id, row.athlete_id): row.place for row in medal_rows
    }
    return raw_by_match, ratings, averages, medal_places


def normalize_match_stage(raw):
    if not raw or not str(raw).strip():
        return "unknown"
    value = normalize(str(raw)).replace("-", " ")
    if re.search(r"\bsemi ?final\b", value):
        return "semifinal"
    if re.search(r"\bquarter ?final\b", value):
        return "quarterfinal"
    if re.search(r"\b(round of 16|round 16|eighth final)\b", value):
        return "round_of_16"
    if re.search(r"\b(consolation|repechage|bronze)\b", value):
        return "consolation"
    if re.search(r"\b(opening round|first round|round 1)\b", value):
        return "opening_round"
    if re.search(r"\bfinal\b", value):
        return "final"
    return "other"


def _display_name(participant):
    athlete = participant.athlete
    return athlete.personal_name or athlete.name


def _category_key(division):
    return (
        bool(division.gi),
        division.gender,
        division.age,
        division.belt,
        division.weight,
    )


def _win_probability(rating, opponent_rating):
    if rating is None or opponent_rating is None:
        return None
    return EloCompetitor(rating).expected_score(EloCompetitor(opponent_rating))


def _participant_snapshot(participant, opponent, division, ratings, medal_place, as_of):
    default = division_default_rating(division.belt, division.age)
    key = (participant.athlete_id, *_category_key(division))
    current = ratings.get(key)
    top_percent = rating_top_percent(current.percentile) if current else None
    current_standing = None
    if current is not None and current.rank is not None and top_percent is not None:
        current_standing = {
            "rating": round(current.rating),
            "rank": current.rank,
            "top_percent": top_percent,
            "elite_tier": (
                None
                if division.belt in NON_ELITE_BELTS
                else elite_tier(current.percentile)
            ),
            "category": {
                "gi": bool(division.gi),
                "gender": division.gender,
                "age": division.age,
                "belt": division.belt,
                "weight": division.weight,
            },
            "as_of": as_of,
        }
    rating_at_match = (
        round(participant.start_rating)
        if participant.start_rating is not None
        else None
    )
    return {
        "athlete_id": str(participant.athlete_id),
        "display_name": _display_name(participant),
        "team": participant.team.name if participant.team else None,
        "rating_at_match": rating_at_match,
        "win_probability": _win_probability(
            participant.start_rating,
            opponent.start_rating if opponent is not None else None,
        ),
        "medal_place": medal_place,
        "rating_maturity": rating_maturity(participant.start_match_count),
        "rating_above_division_default": (
            round(participant.start_rating - default, 2)
            if participant.start_rating is not None and default is not None
            else None
        ),
        "current_standing": current_standing,
    }


def _score_line(values):
    return {field: values.get(field, 0) for field in SCORE_FIELDS}


def _role_score(state, role_keys):
    if not role_keys:
        return None
    return {
        "subject": _score_line(state[role_keys["subject"]]),
        "opponent": _score_line(state[role_keys["opponent"]]),
    }


def _score_rank(line):
    return (line["points"], line["advantages"], -line["penalties"])


def _significance(before, after, action_key, opponent_key):
    if action_key is None or opponent_key is None:
        return {
            "created_tie": None,
            "broke_tie": None,
            "took_lead": None,
            "extended_lead": None,
            "reduced_deficit": None,
        }
    before_action = _score_rank(before[action_key])
    before_opponent = _score_rank(before[opponent_key])
    after_action = _score_rank(after[action_key])
    after_opponent = _score_rank(after[opponent_key])
    before_cmp = (before_action > before_opponent) - (before_action < before_opponent)
    after_cmp = (after_action > after_opponent) - (after_action < after_opponent)
    improved = after_action > before_action
    return {
        "created_tie": before_cmp != 0 and after_cmp == 0,
        "broke_tie": before_cmp == 0 and after_cmp != 0,
        "took_lead": before_cmp <= 0 and after_cmp > 0,
        "extended_lead": before_cmp > 0 and after_cmp > 0 and improved,
        "reduced_deficit": before_cmp < 0 and after_cmp < 0 and improved,
    }


def _time_seconds(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+:\d{2}", value):
        return None
    minutes, seconds = value.split(":")
    if int(seconds) > 59:
        return None
    return int(minutes) * 60 + int(seconds)


def _participant_key_map(match):
    return {
        "red" if participant.red else "blue": participant
        for participant in match.participants
    }


def _role_context(match, subject_id):
    participants = list(match.participants)
    if subject_id is None:
        return None, None, ["subject_role_unavailable"]
    subjects = [row for row in participants if row.athlete_id == subject_id]
    opponents = [row for row in participants if row.athlete_id != subject_id]
    if len(subjects) != 1 or len(opponents) != 1:
        return None, None, ["ambiguous_participant_roles"]
    return subjects[0], opponents[0], []


def _match_moments(match, payload, subject, opponent):
    participant_keys = _participant_key_map(match)
    key_by_athlete = {row.athlete_id: key for key, row in participant_keys.items()}
    role_keys = (
        {
            "subject": key_by_athlete[subject.athlete_id],
            "opponent": key_by_athlete[opponent.athlete_id],
        }
        if subject is not None and opponent is not None
        else None
    )
    state = {
        "red": {field: 0 for field in SCORE_FIELDS},
        "blue": {field: 0 for field in SCORE_FIELDS},
    }
    moments = []
    if match.video_start_offset_seconds is not None:
        moments.append(
            {
                "moment_id": f"{match.id}:match_start:{match.video_start_offset_seconds}",
                "match_id": str(match.id),
                "event_type": "match_start",
                "match_time": payload.get("matchTime"),
                "time_remaining_seconds": _time_seconds(payload.get("matchTime")),
                "video_offset_seconds": match.video_start_offset_seconds,
                "video_lead_seconds": match_detail_video_lead_seconds(
                    {"kind": "match_start"}
                ),
                "action_athlete_id": None,
                "action_role": None,
                "action_by_subject": None,
                "score_category": None,
                "score_delta": None,
                "score_before": None,
                "score_after": None,
                "significance": None,
                "ending": None,
                "warnings": [],
            }
        )

    for event_index, event in enumerate(payload.get("events") or []):
        if event.get("kind") != "score":
            continue
        for action_index, action in enumerate(event.get("actions") or []):
            if action.get("kind") != "score":
                continue
            participant_key = action.get("participantKey")
            participant = participant_keys.get(participant_key)
            category = action.get("category")
            delta = action.get("delta")
            if (
                participant is None
                or category not in SCORE_CATEGORIES
                or not isinstance(delta, int)
            ):
                continue
            before = {key: dict(value) for key, value in state.items()}
            state[participant_key][category] += delta
            after = {key: dict(value) for key, value in state.items()}
            role = None
            if subject is not None:
                role = (
                    "subject"
                    if participant.athlete_id == subject.athlete_id
                    else "opponent"
                )
            other_key = "blue" if participant_key == "red" else "red"
            offset = event.get("videoOffsetSeconds")
            moments.append(
                {
                    "moment_id": f"{match.id}:score:{offset}:{event_index}:{action_index}",
                    "match_id": str(match.id),
                    "event_type": "score",
                    "match_time": event.get("time"),
                    "time_remaining_seconds": _time_seconds(event.get("time")),
                    "video_offset_seconds": offset,
                    "video_lead_seconds": event.get("videoLeadSeconds"),
                    "action_athlete_id": str(participant.athlete_id),
                    "action_role": role,
                    "action_by_subject": role == "subject" if role else None,
                    "score_category": category,
                    "score_delta": delta,
                    "score_before": _role_score(before, role_keys),
                    "score_after": _role_score(after, role_keys),
                    "significance": _significance(
                        before, after, participant_key, other_key
                    ),
                    "ending": None,
                    "warnings": [],
                }
            )

    final = next(
        (
            event
            for event in reversed(payload.get("events") or [])
            if event.get("kind") == "final"
        ),
        None,
    )
    if final and final.get("videoOffsetSeconds") is not None:
        method = final.get("endingMethod")
        event_type = None
        if method == "DQ":
            event_type = "dq"
        elif method == "Submission":
            event_type = "submission"
        elif final.get("time") == "0:00":
            event_type = "decision"
        if event_type:
            winner = next((row for row in match.participants if row.winner), None)
            winner_role = None
            if winner is not None and subject is not None:
                winner_role = (
                    "subject" if winner.athlete_id == subject.athlete_id else "opponent"
                )
            moments.append(
                {
                    "moment_id": f"{match.id}:{event_type}:{final.get('videoOffsetSeconds')}",
                    "match_id": str(match.id),
                    "event_type": event_type,
                    "match_time": final.get("time"),
                    "time_remaining_seconds": _time_seconds(final.get("time")),
                    "video_offset_seconds": final.get("videoOffsetSeconds"),
                    "video_lead_seconds": final.get("videoLeadSeconds"),
                    "action_athlete_id": str(winner.athlete_id) if winner else None,
                    "action_role": winner_role,
                    "action_by_subject": (
                        winner_role == "subject" if winner_role else None
                    ),
                    "score_category": None,
                    "score_delta": None,
                    "score_before": None,
                    "score_after": None,
                    "significance": None,
                    "ending": {
                        "method": method,
                        "amount": final.get("endingMethodAmount"),
                        "winner_athlete_id": str(winner.athlete_id) if winner else None,
                        "winner_role": winner_role,
                    },
                    "warnings": [] if winner else ["winner_unavailable"],
                }
            )
    return moments


def _filtered_moments(moments, filters):
    selected = [
        moment
        for moment in moments
        if filters["event_type"] == "all"
        or moment["event_type"] == filters["event_type"]
    ]
    if filters["event_type"] == "score":
        if filters["score_category"]:
            selected = [
                row
                for row in selected
                if row["score_category"] == filters["score_category"]
            ]
        if filters["score_delta"] is not None:
            selected = [
                row for row in selected if row["score_delta"] == filters["score_delta"]
            ]
    return selected


def _participant_final_score(match, participant):
    if participant is None:
        return None
    position = participant.scoreboard_position or (
        "top" if participant.red else "bottom"
    )
    if position not in {"top", "bottom"}:
        return None
    return {
        field: getattr(match, f"final_{position}_{field}") for field in SCORE_FIELDS
    }


def _result(match, payload, subject, opponent):
    final = next(
        (
            event
            for event in reversed(payload.get("events") or [])
            if event.get("kind") == "final"
        ),
        {},
    )
    winner = next((row for row in match.participants if row.winner), None)
    return {
        "method": final.get("endingMethod"),
        "amount": final.get("endingMethodAmount"),
        "match_time_seconds": match.final_match_time_seconds,
        "winner_athlete_id": str(winner.athlete_id) if winner else None,
        "final_score": (
            {
                "subject": _participant_final_score(match, subject),
                "opponent": _participant_final_score(match, opponent),
            }
            if subject is not None and opponent is not None
            else None
        ),
    }


def build_highlight_discovery(args):
    filters = _parse_filters(args)
    matches = _candidate_matches(filters)
    raw_by_match, ratings, averages, medal_places = _bulk_context(matches)
    as_of = _iso_datetime(datetime.now(timezone.utc))
    response_matches = []
    remaining = filters["limit"]
    omitted_total = 0
    omitted_match_count = 0

    for match in matches:
        raw_events = raw_by_match.get(match.id) or []
        if not raw_events or match.division is None:
            continue
        payload = build_match_detail_payload(match, raw_events)
        source_url = payload.get("videoSourceUrl")
        if not source_url:
            continue
        subject, opponent, warnings = _role_context(match, filters["athlete_id"])
        all_moments = _match_moments(match, payload, subject, opponent)
        selected = _filtered_moments(all_moments, filters)
        if not selected:
            continue
        if remaining <= 0:
            omitted_total += len(selected)
            omitted_match_count += 1
            continue
        returned = selected[:remaining]
        omitted = len(selected) - len(returned)
        omitted_total += omitted

        division = match.division
        ordered_participants = sorted(
            match.participants, key=lambda row: (not row.red, str(row.id))
        )
        participants = [
            _participant_snapshot(
                row,
                next(
                    (other for other in ordered_participants if other.id != row.id),
                    None,
                ),
                division,
                ratings,
                medal_places.get((match.event_id, match.division_id, row.athlete_id)),
                as_of,
            )
            for row in ordered_participants
        ]
        by_id = {row["athlete_id"]: row for row in participants}
        default = division_default_rating(division.belt, division.age)
        average = averages.get(_category_key(division))
        subject_payload = by_id.get(str(subject.athlete_id)) if subject else None
        opponent_payload = by_id.get(str(opponent.athlete_id)) if opponent else None
        score_count = len([row for row in all_moments if row["event_type"] == "score"])
        finish_types = {
            row["event_type"]
            for row in all_moments
            if row["event_type"] in {"submission", "decision", "dq"}
        }
        response_matches.append(
            {
                "match_id": str(match.id),
                "happened_at": _iso_datetime(match.happened_at),
                "event": {
                    "event_id": str(match.event.id),
                    "name": match.event.name,
                },
                "division": {
                    "gi": bool(division.gi),
                    "gender": division.gender,
                    "age": division.age,
                    "belt": division.belt,
                    "weight": division.weight,
                },
                "division_size": match.division_size,
                "rating_context": {
                    "division_default_rating": default,
                    "current_division_average_rating": (
                        round(average, 2) if average is not None else None
                    ),
                    "as_of": as_of,
                },
                "participants": participants,
                "subject": subject_payload,
                "opponent": opponent_payload,
                "subject_won": subject.winner if subject else None,
                "rating_difference": (
                    round(subject.start_rating - opponent.start_rating, 2)
                    if subject is not None
                    and opponent is not None
                    and subject.start_rating is not None
                    and opponent.start_rating is not None
                    else None
                ),
                "match_stage": normalize_match_stage(match.match_location),
                "match_stage_raw": match.match_location,
                "result": _result(match, payload, subject, opponent),
                "coverage": {
                    "has_match_start": any(
                        row["event_type"] == "match_start" for row in all_moments
                    ),
                    "score_moment_count": score_count,
                    "has_finish": bool(finish_types),
                    "finish_type": next(iter(finish_types), None),
                    "complete_timeline_available": (
                        filters["event_type"] == "all" and omitted == 0
                    ),
                    "returned_moment_count": len(returned),
                    "available_moment_count": len(all_moments),
                    "more_moments_omitted": omitted > 0,
                    "video_warning": None,
                },
                "video": {"source_url": source_url},
                "moments": returned,
                "warnings": warnings,
            }
        )
        remaining -= len(returned)

    public_filters = {
        **filters,
        "athlete_id": str(filters["athlete_id"]) if filters["athlete_id"] else None,
        "match_id": str(filters["match_id"]) if filters["match_id"] else None,
    }
    moment_count = sum(len(row["moments"]) for row in response_matches)
    return {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "filters": public_filters,
        "match_count": len(response_matches),
        "moment_count": moment_count,
        "omitted_moment_count": omitted_total,
        "omitted_match_count": omitted_match_count,
        "matches": response_matches,
    }
