from sqlalchemy.sql import text
from datetime import datetime
from urllib.parse import quote


def load_livestream_links(session, event_ids, registrations=False):
    tournament_days = {}

    # Build parameterized IN clause for event_ids
    event_id_params = {f"eid_{i}": eid for i, eid in enumerate(event_ids)}
    event_id_placeholders = ", ".join([f":eid_{i}" for i in range(len(event_ids))])

    if registrations:
        event_results = session.execute(
            text(
                f"""
            SELECT r.event_id, r.event_start_date
            FROM registration_links r
            WHERE r.event_id IN ({event_id_placeholders})
            """
            ),
            event_id_params,
        )
        for ibjjf_id, start_date in event_results:
            start_date_date = start_date
            if isinstance(start_date, str):
                start_date_date = datetime.fromisoformat(start_date)
            tournament_days[ibjjf_id] = start_date_date.date()
    else:
        event_results = session.execute(
            text(
                f"""
            SELECT e.ibjjf_id, MIN(m.happened_at) AS min_date
            FROM events e
            JOIN matches m ON e.id = m.event_id
            WHERE e.ibjjf_id IN ({event_id_placeholders})
            GROUP BY e.ibjjf_id
            """
            ),
            event_id_params,
        )
        for ibjjf_id, min_date in event_results:
            min_date_date = min_date
            if isinstance(min_date, str):
                min_date_date = datetime.fromisoformat(min_date)
            tournament_days[ibjjf_id] = min_date_date.date()

    live_streams = {}
    for (
        event_id,
        day_number,
        mat_number,
        link,
        start_hour,
        start_minute,
        start_seconds,
        end_hour,
        end_minute,
        drift_factor,
        hide_all,
    ) in session.execute(
        text(
            f"""
        SELECT event_id, day_number, mat_number, link, start_hour, start_minute, start_seconds, end_hour, end_minute, drift_factor, hide_all
        FROM live_streams
        WHERE event_id IN ({event_id_placeholders})
        ORDER BY event_id, day_number, mat_number, start_hour, start_minute, start_seconds
        """
        ),
        event_id_params,
    ):
        live_streams.setdefault((event_id, day_number, mat_number), []).append(
            (
                link,
                start_hour,
                start_minute,
                start_seconds,
                end_hour,
                end_minute,
                drift_factor,
                hide_all,
            )
        )

    flo_event_tags = {
        event_id: tag
        for event_id, tag in session.execute(
            text(
                f"""
            SELECT event_id, tag
            FROM flo_event_tags
            WHERE event_id IN ({event_id_placeholders})
            """
            ),
            event_id_params,
        )
    }

    return {
        "tournament_days": tournament_days,
        "live_streams": live_streams,
        "flo_event_tags": flo_event_tags,
    }


SPECIAL_SEARCH_NAMES = {
    "Andy Tomas Murasaki Pereira": "Andy Murasaki",
    "Erich Munis dos Santos": "Erich Munis",
    "Pedro Henrique Pinheiro M. de Souza": "Pedro Machado",
    "Jackson Nagai Hatchwell Junior": "Jackson Nagai",
    "Edwin Ocasio": "Ocasio",  # inconsistent, sometimes Junny Ocasio sometimes Edwin Ocasio or Edwin Junny Ocasio
}


def name_components(name):
    return [
        n
        for n in name.strip().split()
        if n.lower() not in ["jr.", "sr.", "jr", "sr", "2nd", "3rd", "ii", "iii"]
        and not n.startswith('"')
        and len(n.replace(".", "")) > 1
    ]


def get_search_name(full_name):
    if full_name in SPECIAL_SEARCH_NAMES:
        return SPECIAL_SEARCH_NAMES[full_name]
    names = name_components(full_name)
    if len(full_name) > 32:
        # use first two names only to avoid cutoff
        return " ".join(names[:2])
    else:
        # use first and last name
        return " ".join([names[0], names[-1]])


def get_livestream_link(
    livestream_links,
    ibjjf_id,
    winner_name,
    loser_name,
    happened_at_datetime,
    match_location,
):
    tournament_days = livestream_links["tournament_days"]
    live_streams = livestream_links["live_streams"]
    flo_event_tags = livestream_links["flo_event_tags"]

    if ibjjf_id in flo_event_tags and winner_name and loser_name:
        tag = flo_event_tags[ibjjf_id]
        if winner_name and loser_name:
            winner_last_name = get_search_name(
                winner_name,
            )
            loser_last_name = get_search_name(
                loser_name,
            )
            return f"https://www.flograppling.com/events/{tag}/videos?openInBrowser=1&search={quote(winner_last_name)}%20vs%20{quote(loser_last_name)}"
    elif len(live_streams):
        event_start_day = tournament_days.get(ibjjf_id)
        if event_start_day:
            match_day = happened_at_datetime.date()
            match_hour = happened_at_datetime.hour
            match_minute = happened_at_datetime.minute
            day_number = (match_day - event_start_day).days + 1
            mat_number = match_location
            mat_number_int = None
            if mat_number:
                try:
                    mat_number_int = int(mat_number.split()[-1])
                except ValueError:
                    mat_number_int = None
            if mat_number_int is not None:
                livestream_info_list = live_streams.get(
                    (ibjjf_id, day_number, mat_number_int)
                )
                if livestream_info_list:
                    for index, livestream_info in enumerate(livestream_info_list):
                        (
                            link,
                            start_hour,
                            start_minute,
                            start_seconds,
                            end_hour,
                            end_minute,
                            drift_factor,
                            hide_all,
                        ) = livestream_info

                        cut_seconds = 0
                        (
                            start_hour_with_link,
                            start_minute_with_link,
                            start_second_with_link,
                        ) = (start_hour, start_minute, start_seconds)
                        start_set = False
                        if index > 0:
                            for i in range(index):
                                (
                                    prevlink,
                                    lsh,
                                    lsm,
                                    lss,
                                    eh,
                                    em,
                                    _,
                                    _,
                                ) = livestream_info_list[i]
                                (
                                    _,
                                    sh,
                                    sm,
                                    ss,
                                    _,
                                    _,
                                    _,
                                    _,
                                ) = livestream_info_list[i + 1]

                                if prevlink == link:
                                    missing_seconds = (sh * 3600 + sm * 60 + ss) - (
                                        eh * 3600 + em * 60
                                    )
                                    cut_seconds += missing_seconds

                                    if not start_set:
                                        start_hour_with_link = lsh
                                        start_minute_with_link = lsm
                                        start_second_with_link = lss
                                        start_set = True

                        match_seconds = match_hour * 3600 + match_minute * 60
                        start_seconds_for_offset = (
                            start_hour_with_link * 3600
                            + start_minute_with_link * 60
                            + start_second_with_link
                        )
                        stream_start_seconds = (
                            start_hour * 3600 + start_minute * 60 + start_seconds
                        )
                        end_seconds = end_hour * 3600 + end_minute * 60

                        if (
                            match_seconds >= stream_start_seconds
                            and match_seconds < end_seconds
                        ):
                            time_offset_seconds = (
                                match_seconds - start_seconds_for_offset - cut_seconds
                            )

                            if time_offset_seconds <= 0:
                                time_offset_seconds = 1

                            time_offset_seconds = round(
                                time_offset_seconds * drift_factor
                            )

                            if not flo_event_tags.get(ibjjf_id):
                                link += "&t=" + str(time_offset_seconds) + "s"

                            if hide_all:
                                return None

                            return link

    return None
