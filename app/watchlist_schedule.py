"""Pure order-of-fights parsing. Only mat cards establish athlete presence."""

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, parse_qs

from bs4 import BeautifulSoup

BASE = "https://www.bjjcompsystem.com"


class SourceError(ValueError):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


def source_url(href, event_id=None):
    url = urlsplit(urljoin(BASE, href))
    match = re.fullmatch(r"/tournaments/(\d+)/tournament_days/(\d+)", url.path)
    if url.scheme != "https" or url.netloc != "www.bjjcompsystem.com" or not match:
        return None
    if event_id is not None and match[1] != str(event_id):
        return None
    query = parse_qs(url.query)
    page = query.get("page", ["1"])[0]
    if not page.isdigit() or not 1 <= int(page) <= 500:
        return None
    return f"{BASE}{url.path}?page={int(page)}&locale=en"


def homepage_links(html):
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for a in soup.select("a[href]"):
        url = source_url(a["href"])
        if url:
            links.setdefault(urlsplit(url).path.split("/")[2], url)
    if not links:
        raise SourceError("unrecognized_discovery")
    return links


def day_date(label, start, end):
    match = re.search(r"\b(\d{2})/(\d{2})\b", label)
    if not match:
        raise SourceError("missing_day_date")
    candidates = []
    for year in range(start.year, end.year + 1):
        try:
            value = datetime(year, int(match[1]), int(match[2])).date()
            if start.date() <= value <= end.date():
                candidates.append(value)
        except ValueError:
            pass
    if len(candidates) != 1:
        raise SourceError("ambiguous_day_date")
    return candidates[0]


def discover_days(soup, event_id, start, end):
    days = {}
    for a in soup.select("a[href]"):
        url = source_url(a["href"], event_id)
        label = a.get_text(" ", strip=True)
        if not url or not re.search(r"\bDay\s+\d+", label, re.I):
            continue
        day_id = urlsplit(url).path.split("/")[-1]
        mats = re.search(r"\((\d+)\s+Mats?\)", label, re.I)
        value = {
            "day_id": day_id,
            "date": day_date(label, start, end).isoformat(),
            "mats": int(mats[1]) if mats else None,
            "url": source_url(urlsplit(url).path, event_id),
        }
        if day_id in days and days[day_id] != value:
            raise SourceError("changed_days")
        days[day_id] = value
    if not days:
        raise SourceError("missing_days")
    return days


def text_at(node, selector):
    found = node.select_one(selector)
    return found.get_text(" ", strip=True) if found else ""


def parse_side(node):
    # Placeholder elements also have competitor-N ids: those are NOT identities.
    placeholder = text_at(node, ".match-card__child-description")
    if placeholder:
        where = text_at(node, ".match-card__child-where")
        return {
            "ibjjf_id": None,
            "description": " · ".join(p for p in (placeholder, where) if p),
            "name": None,
            "team": None,
        }
    name = text_at(node, ".match-card__competitor-name")
    identity = re.fullmatch(r"competitor-(\d+)", node.get("id", ""))
    if not name or not identity:
        raise SourceError("invalid_competitor")
    return {
        "ibjjf_id": identity[1],
        "name": name,
        "team": text_at(node, ".match-card__club-name"),
        "description": None,
    }


def parse_page(html, url, event_id, day):
    soup = BeautifulSoup(html, "html.parser")
    columns = soup.select(".sliding-columns__column")
    if not columns:
        raise SourceError("unrecognized_schedule")
    mats, matches, pages = [], [], set()
    for column in columns:
        header = re.fullmatch(
            r"Mat\s+(\d+)", text_at(column, ".grid-column__header"), re.I
        )
        container = column.select_one("ul.tournament-day__mats")
        if not header or container is None:
            raise SourceError("invalid_mat")
        mat = int(header[1])
        if mat in mats:
            raise SourceError("duplicate_mat")
        mats.append(mat)
        for card in container.find_all("li", recursive=False):
            fight = re.fullmatch(
                r"FIGHT\s+(\d+)", text_at(card, ".match-header__fight"), re.I
            )
            sides = card.select(".match-card__competitor")
            category = text_at(card, ".match-header__category-name")
            if not fight or len(sides) != 2 or not category:
                raise SourceError("invalid_fight")
            when = text_at(card, ".match-header__when")
            clock = re.search(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", when, re.I)
            local_time = None
            if clock:
                try:
                    local_time = datetime.strptime(
                        re.sub(r"\s*([AP]M)$", r" \1", clock[1].upper()),
                        "%I:%M %p",
                    ).strftime("%H:%M")
                except ValueError as exc:
                    raise SourceError("invalid_time") from exc
            matches.append(
                {
                    "event_id": str(event_id),
                    "day_id": day["day_id"],
                    "local_date": day["date"],
                    "mat": mat,
                    "fight_number": int(fight[1]),
                    "local_time": local_time,
                    "division": category,
                    "sides": [parse_side(s) for s in sides],
                    "source_order": len(matches),
                }
            )
    for a in soup.select("a[href]"):
        target = source_url(urljoin(url, a["href"]), event_id)
        if target and urlsplit(target).path == urlsplit(url).path:
            pages.add(target)
        elif (
            "page=" in a["href"]
            and not target
            and (
                "tournament_days" in a["href"]
                or urlsplit(urljoin(url, a["href"])).path == urlsplit(url).path
            )
        ):
            raise SourceError("invalid_pagination")
    return {"matches": matches, "mats": mats, "pages": sorted(pages), "soup": soup}


def scan_tournament(fetch, initial_url, event, today, fetch_many=None):
    """Restart topology once; never return a partial generation as a snapshot."""
    for attempt in range(2):
        try:
            return _scan(fetch, initial_url, event, today, fetch_many)
        except SourceError as exc:
            if attempt or exc.code not in {
                "changed_days",
                "duplicate_mat",
                "missing_mats",
            }:
                raise


def _scan(fetch, initial_url, event, today, fetch_many=None):
    first = fetch(initial_url)
    days = discover_days(
        BeautifulSoup(first, "html.parser"),
        event["event_id"],
        event["start"],
        event["end"],
    )
    all_matches, coverage = [], []
    known_dates = {d["date"] for d in days.values()}
    date = max(today, event["start"].date())
    while date <= event["end"].date():
        if date.isoformat() not in known_dates:
            coverage.append(
                {
                    "date": date.isoformat(),
                    "state": "unpublished",
                    "pages": [],
                    "mats": [],
                }
            )
        date += timedelta(days=1)
    for day in sorted(days.values(), key=lambda d: (d["date"], d["day_id"])):
        if day["date"] < today.isoformat():
            continue
        pending, visited, mats, fights = {day["url"]}, set(), set(), set()
        if day["mats"]:
            pending.update(
                day["url"].replace("page=1&", f"page={p}&")
                for p in range(1, (day["mats"] + 3) // 4 + 1)
            )
        while pending:
            batch = sorted(pending - visited)[:2]
            if not batch:
                break
            pending.difference_update(batch)
            urls = [url for url in batch if url != initial_url]
            bodies = fetch_many(urls) if fetch_many else [fetch(url) for url in urls]
            html_by_url = dict(zip(urls, bodies))
            html_by_url[initial_url] = first
            for url in batch:
                page = parse_page(html_by_url[url], url, event["event_id"], day)
                if (
                    discover_days(
                        page["soup"], event["event_id"], event["start"], event["end"]
                    )
                    != days
                ):
                    raise SourceError("changed_days")
                if mats.intersection(page["mats"]):
                    raise SourceError("duplicate_mat")
                mats.update(page["mats"])
                visited.add(url)
                pending.update(set(page["pages"]) - visited - set(batch))
                for match in page["matches"]:
                    key = (match["mat"], match["fight_number"])
                    if key in fights:
                        raise SourceError("duplicate_fight")
                    fights.add(key)
                    all_matches.append(match)
        if day["mats"] is not None and mats != set(range(1, day["mats"] + 1)):
            raise SourceError("missing_mats")
        coverage.append(
            {**day, "state": "complete", "pages": sorted(visited), "mats": sorted(mats)}
        )
    return all_matches, coverage, days
