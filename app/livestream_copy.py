from sqlalchemy import func

from models import Event, LiveStream, Match, RegistrationLink


STREAM_FIELDS = (
    "platform",
    "mat_number",
    "day_number",
    "start_hour",
    "start_minute",
    "start_seconds",
    "end_hour",
    "end_minute",
    "drift_factor",
    "hide_all",
    "link",
)


def copy_sources(session, current_event_id):
    dates = (
        session.query(
            Event.ibjjf_id.label("event_id"), func.min(Match.happened_at).label("date")
        )
        .join(Match, Match.event_id == Event.id)
        .group_by(Event.ibjjf_id)
        .subquery()
    )
    registrations = (
        session.query(
            RegistrationLink.event_id.label("event_id"),
            func.max(RegistrationLink.name).label("name"),
            func.max(RegistrationLink.event_start_date).label("date"),
        )
        .group_by(RegistrationLink.event_id)
        .subquery()
    )
    event_date = func.coalesce(dates.c.date, registrations.c.date)
    rows = (
        session.query(
            LiveStream.event_id,
            func.coalesce(Event.name, registrations.c.name, LiveStream.event_id).label(
                "name"
            ),
            event_date.label("date"),
        )
        .outerjoin(Event, Event.ibjjf_id == LiveStream.event_id)
        .outerjoin(dates, dates.c.event_id == LiveStream.event_id)
        .outerjoin(registrations, registrations.c.event_id == LiveStream.event_id)
        .filter(LiveStream.event_id != current_event_id, LiveStream.day_number >= 1)
        .distinct()
        .order_by(event_date.desc().nullslast(), LiveStream.event_id.desc())
        .limit(6)
        .all()
    )
    days = {}
    for event_id, day in (
        session.query(LiveStream.event_id, LiveStream.day_number)
        .filter(
            LiveStream.event_id.in_([row.event_id for row in rows]),
            LiveStream.day_number >= 1,
        )
        .distinct()
        .order_by(LiveStream.day_number)
    ):
        days.setdefault(event_id, []).append(day)
    return [
        dict(
            event_id=row.event_id,
            name=row.name,
            date=row.date.strftime("%Y-%m-%d") if row.date else "",
            days=days[row.event_id],
        )
        for row in rows
    ]


def copy_streams(session, source_event_id, source_day, target_event_id):
    if (
        not target_event_id
        or source_event_id == target_event_id
        or not source_day
        or source_day < 1
    ):
        raise ValueError("Select another event and a valid source day.")
    sources = (
        session.query(LiveStream)
        .filter_by(
            event_id=source_event_id,
            day_number=source_day,
        )
        .all()
    )
    if not sources:
        raise ValueError("The selected event has no streams for that day.")
    existing = {
        tuple(getattr(stream, field) for field in STREAM_FIELDS)
        for stream in session.query(LiveStream).filter_by(event_id=target_event_id)
    }
    count = 0
    for source in sources:
        values = {field: getattr(source, field) for field in STREAM_FIELDS}
        values["day_number"] = max(1, source_day - 1)
        key = tuple(values[field] for field in STREAM_FIELDS)
        if key not in existing:
            session.add(LiveStream(event_id=target_event_id, **values))
            existing.add(key)
            count += 1
    return count
