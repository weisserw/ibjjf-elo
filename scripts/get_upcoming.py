#!/usr/bin/env python3
import sys
import os
import logging
import traceback
from datetime import datetime
import re
import requests

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from models import RegistrationLink
from routes.brackets import import_registration_link, normalize_registration_link
from normalize import normalize

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("get_upcoming")


def parse_event_dates(date_str, current_year, current_month):
    # Example: "Nov 22 - Nov 23" or "Dec 30 - Jan 2"
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }
    # Remove any trailing '*' from day numbers
    parts = date_str.split("-")
    if len(parts) == 2:
        start = parts[0].strip()
        end = parts[1].strip()
        start_month, start_day = start.split(" ")
        end_month, end_day = end.split(" ") if " " in end else (start_month, end)
        start_day = start_day.rstrip("*")
        end_day = end_day.rstrip("*")
        start_month_num = months[start_month]
        end_month_num = months[end_month]
        start_day = int(start_day)
        end_day = int(end_day)
        # If start month is before current month, it's next year
        if start_month_num < current_month:
            start_year = current_year + 1
        else:
            start_year = current_year
        if end_month_num < current_month:
            end_year = current_year + 1
        else:
            end_year = current_year
        start_date = datetime(start_year, start_month_num, start_day)
        end_date = datetime(end_year, end_month_num, end_day)
        return start_date, end_date
    else:
        # fallback: single day event
        start_month, start_day = date_str.split(" ")
        start_day = start_day.rstrip("*")
        start_month_num = months[start_month]
        start_day = int(start_day)
        if start_month_num < current_month:
            year = current_year + 1
        else:
            year = current_year
        dt = datetime(year, start_month_num, start_day)
        return dt, dt


def main():
    try:
        from app import db, app

        total_competitors = 0

        with app.app_context():
            url = "https://ibjjf.com/api/v1/events/upcomings.json"
            log.info(f"Downloading {url}")
            headers = {
                "accept": "application/json, text/plain, */*",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-US,en;q=0.9,ja-JP;q=0.8,ja;q=0.7",
                "cache-control": "no-cache",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "referer": "https://ibjjf.com/events/championships",
                "sec-ch-ua": '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"macOS"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
                "x-requested-with": "XMLHttpRequest",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            championships = data.get("championships", [])
            log.info(f"Found {len(championships)} events")
            now = datetime.now()
            for event in championships:
                name = event.get("name")
                url_logo = event.get("urlLogo", "")
                m = re.search(r"Logo/(\d+)", url_logo)
                if not m:
                    log.warning(f"Could not parse event ID from urlLogo: {url_logo}")
                    continue
                event_id = m.group(1)
                event_link = normalize_registration_link(
                    f"https://www.ibjjfdb.com/ChampionshipResults/{event_id}/PublicRegistrations"
                )
                date_str = event.get("eventIntervalDays", "")
                if not date_str:
                    log.warning(f"No eventIntervalDays for event {name}")
                    continue
                start_date, end_date = parse_event_dates(date_str, now.year, now.month)

                link = (
                    db.session.query(RegistrationLink)
                    .filter(RegistrationLink.link == event_link)
                    .first()
                )
                if not link:
                    link = RegistrationLink(
                        name=name,
                        normalized_name=normalize(name),
                        updated_at=datetime(2022, 1, 1),
                        link=event_link,
                        event_start_date=start_date,
                        event_end_date=end_date,
                    )
                    db.session.add(link)
                    db.session.commit()
                    log.info(f"Found new tournament {name} ({event_link})")

                competitor_count = import_registration_link(
                    event_link, background=False
                )["total_competitors"]
                log.info(
                    f"Imported tournament {name} ({event_link}), {competitor_count} competitors"
                )
                total_competitors += competitor_count
            db.session.commit()

        log.info(f"Total competitors found: {total_competitors}")
    except Exception as e:
        log.error(f"Unhandled exception: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
