from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from models import Match


def refresh_match_division_sizes(session, event_ids):
    event_ids = list({event_id for event_id in event_ids if event_id is not None})
    if not event_ids:
        return

    session.query(Match).filter(
        Match.event_id.in_(event_ids),
        Match.match_number.is_(None),
    ).update({Match.division_size: None}, synchronize_session=False)

    matching_match = aliased(Match)
    division_size = (
        select(func.max(matching_match.match_number))
        .where(
            matching_match.event_id == Match.event_id,
            matching_match.division_id == Match.division_id,
            matching_match.match_number.isnot(None),
        )
        .correlate(Match)
        .scalar_subquery()
    )

    session.query(Match).filter(
        Match.event_id.in_(event_ids),
        Match.match_number.isnot(None),
    ).update({Match.division_size: division_size}, synchronize_session=False)
    session.flush()
