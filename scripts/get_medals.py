#!/usr/bin/env python3
"""Scrape IBJJF and CBJJ medal results into a single CSV.

Output columns match the `result_medals` table column order so the CSV can be
loaded via `\\copy` with no column list:

    id, event_name, event_ibjjf_id, division, athlete_name, team_name, place,
    source, event_url, scraped_at

`id` is a deterministic UUID5 derived from a hash of every other column except
`scraped_at`, so the same row produces the same primary key across re-scrapes.

Three result-page formats are handled:
  - New format (ibjjfdb.com/ChampionshipResults/<id>/PublicResults), 2012+
  - Old IBJJF format (ibjjf.com/events/results/<slug>), pre-2012
  - Old CBJJ format (cbjj.com.br or cbjj-production.herokuapp.com/events/results/<slug>)

CBJJ events that overlap with IBJJF are de-duped by championship ID (2012+)
or by mapped English name + year (pre-2012); see CBJJ_NAME_MAP below.

------------------------------------------------------------------------------
Loading the resulting CSV into Postgres (truncates the table first):

    psql "$DATABASE_URL" <<'SQL'
    BEGIN;
    TRUNCATE result_medals;
    \\copy result_medals FROM 'medals.csv' WITH (FORMAT csv, HEADER true, FORCE_NOT_NULL (team_name))
    COMMIT;
    SQL

The CSV header row is skipped by `HEADER true`; column order in the CSV
matches the table definition, so no explicit column list is needed.
FORCE_NOT_NULL keeps an empty CSV team_name as the empty string instead of
NULL, since a handful of source rows list no team and team_name is NOT NULL.
------------------------------------------------------------------------------
"""

import argparse
import csv
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))
from constants import (  # noqa: E402
    translate_age_keep_juvenile,
    translate_belt,
    translate_gender,
    translate_weight,
)
from normalize import normalize  # noqa: E402


IBJJF_RESULTS_URL = "https://ibjjf.com/events/results"
CBJJ_RESULTS_URL = "https://cbjj.com.br/events/results"

USER_AGENT = "ibjjf-medals-scraper/1.0 (+https://github.com/weisserw/ibjjf)"
REQUEST_TIMEOUT = 30
REQUEST_DELAY_SECONDS = 0.25
MAX_RETRIES = 2

# Maps CBJJ tournament names (data-n) to the equivalent IBJJF name used on the
# IBJJF results page. Used for de-duping pre-2012 events where the two sites
# host the results separately on their own legacy URLs.
#
# Note: many CBJJ events use the *same* Portuguese name that IBJJF uses (e.g.
# "Campeonato Brasileiro de Jiu-Jitsu"). Those don't need to be mapped — the
# dedup falls back to comparing the original name. Only add entries here when
# the CBJJ name genuinely differs from the IBJJF spelling.
# Extra IBJJF event pages that exist on ibjjfdb.com but are not linked from the
# IBJJF or CBJJ results index pages. Scraped alongside the index-derived links
# whenever IBJJF is being scraped.
EXTRA_IBJJF_LINKS = [
    {
        "tournament": "Campeonato Português de Jiu-Jitsu",
        "year": "2024",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2166/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
    {
        "tournament": "Campeonato Português de Jiu-Jitsu",
        "year": "2023",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2473/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
    {
        "tournament": "Nacional Open Portugal No-Gi",
        "year": "2024",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2661/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
    {
        "tournament": "Nacional Open Portugal",
        "year": "2024",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2660/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
    {
        "tournament": "Nacional Open Portugal No-Gi",
        "year": "2025",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2990/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
    {
        "tournament": "Nacional Open Portugal",
        "year": "2025",
        "url": "https://www.ibjjfdb.com/ChampionshipResults/2989/PublicResults?lang=en-US",
        "source": "ibjjf",
    },
]


CBJJ_NAME_MAP = {
    "Campeonato Brasileiro de Jiu-Jitsu Sem Kimono": "Brazilian National Jiu-Jitsu No-Gi Championship",
    "Campeonato Brasileiro de Jiu-Jitsu (idade 04 a 15 anos)": "Campeonato Brasileiro de Jiu-Jitsu (age 4 to 15)",
    "Campeonato Sul Americano de Jiu-Jitsu": "South American Jiu-Jitsu IBJJF Championship",
    "Campeonato Sul Americano de Jiu-Jitsu Sem kimono": "South American Jiu-Jitsu IBJJF No-Gi Championship",
    "Campeonato Sul Americano de Jiu-Jitsu Sem Kimono": "South American Jiu-Jitsu IBJJF No-Gi Championship",
    "Campeonato Sul Americano de Jiu-Jitsu - Novice": "South American Jiu-Jitsu IBJJF Championship - Novice",
    "Campeonato Sul Americano de Jiu-Jitsu - Crianças": "South American Jiu-Jitsu IBJJF Championship – Kids",
}


# (tournament-label-from-data-n, year-from-data-y, championship-id-from-URL)
# triples for IBJJF index entries we've confirmed are mislabeled — typically
# a Kids/regional event link that accidentally points at a different
# championship's results page, or a phantom year-button that points at a
# different year's real page. Entries here are silently dropped before URL
# dedup, leaving the correctly-labeled sibling link in place.
KNOWN_BAD_LINKS = {
    # IBJJF's index lists this Florianópolis Kids button pointing at
    # /ChampionshipResults/3086/, which is actually the Curitiba Summer
    # No-Gi Championship 2026. Dropping the Florianópolis label preserves
    # the legitimate Curitiba No-Gi scrape.
    ("Kids International IBJJF Jiu-Jitsu Championship - Florianópolis", "2026", "3086"),
    # The "American National Kids" button shares /ChampionshipResults/408/
    # with the main American National IBJJF Jiu-Jitsu Championship 2015 —
    # keep the main label, drop the Kids one. Same mislabel recurs in 2016,
    # 2017, 2018.
    ("American National Kids IBJJF Jiu-Jitsu Championship", "2015", "408"),
    ("American National Kids IBJJF Jiu-Jitsu Championship", "2016", "575"),
    ("American National Kids IBJJF Jiu-Jitsu Championship", "2017", "753"),
    ("American National Kids IBJJF Jiu-Jitsu Championship", "2018", "948"),
    # Same Kids-page-pointing-at-adult-page mistake on British National 2016.
    ("British National Kids IBJJF Jiu-Jitsu Championship", "2016", "555"),
    # Chicago Summer International 2016 Kids button points at the adult page.
    (
        "Chicago Summer Kids International Open IBJJF Jiu-Jitsu Championship",
        "2016",
        "566",
    ),
    # Phantom Madrid 2025 button points at the real Madrid 2026 page (3077);
    # there was no 2025 Madrid Open. Drop the 2025 label, keep 2026.
    ("Madrid International Open IBJJF Jiu-Jitsu Championship", "2025", "3077"),
    # The "Recife Kids 2026" button actually points at /ChampionshipResults/2717/,
    # which is the real Florianópolis Kids 2025 page. Drop the Recife label.
    ("Recife Kids International Open IBJJF Jiu-Jitsu Championship", "2026", "2717"),
    # San Antonio 2026: the No-Gi button mistakenly points at 3121, which is
    # the Gi page. The real No-Gi page is /ChampionshipResults/3122/, reachable
    # from its own correct button. Drop the bad No-Gi label so the Gi entry
    # owns 3121 unambiguously. NOTE: this is the same gi/no-gi shape as the
    # Curitiba/Florianópolis incident — check medals already in the DB for
    # cross-contamination on these events.
    (
        "San Antonio International Open IBJJF Jiu-Jitsu No-Gi Championship",
        "2026",
        "3121",
    ),
}


# UUID5 namespace for hashing medal rows into stable primary keys. This is a
# fixed, randomly-generated UUID — do not change it without re-importing all rows.
RESULT_MEDAL_NAMESPACE = uuid.UUID("3a4f1c1e-2b9d-5e8a-9c4f-7d6e5b3a2c1f")

# CSV columns that contribute to the deterministic row id. scraped_at is
# excluded so a row's id is stable across re-scrapes.
ID_FIELDS = (
    "event_name",
    "event_ibjjf_id",
    "division",
    "athlete_name",
    "team_name",
    "place",
    "source",
    "event_url",
)


def deterministic_id(row):
    """Return a stable UUID5 derived from the row's identifying fields."""
    key = "\x1f".join(str(row.get(f, "")) for f in ID_FIELDS)
    return uuid.uuid5(RESULT_MEDAL_NAMESPACE, key)


def fetch(url, session):
    last_exc = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < MAX_RETRIES:
                time.sleep(1 + attempt)
            continue
    raise last_exc


def make_session():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


# ---------------------------------------------------------------------------
# Index pages: enumerate every (tournament, year, url) tuple.
# ---------------------------------------------------------------------------


def parse_index_page(html, source):
    """Return list of dicts {tournament, year, url, source} from a results index."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for link in soup.find_all("a", class_="event-year-result"):
        name = (link.get("data-n") or "").strip()
        year = (link.get("data-y") or "").strip()
        href = (link.get("href") or "").strip()
        if not name or not year or not href:
            continue
        out.append(
            {
                "tournament": name,
                "year": year,
                "url": href,
                "source": source,
            }
        )
    return out


CHAMPIONSHIP_ID_RE = re.compile(r"/ChampionshipResults/(\d+)/", re.IGNORECASE)


def extract_championship_id(url):
    match = CHAMPIONSHIP_ID_RE.search(url)
    return match.group(1) if match else None


def dedup_links(ibjjf_links, cbjj_links):
    """Return a list of all links from both sources, dropping CBJJ duplicates.

    A CBJJ link is considered a duplicate if:
      - Its URL contains a ChampionshipResults/<id> that we've already seen via IBJJF, OR
      - Its tournament name maps to an IBJJF name (via CBJJ_NAME_MAP) and we've
        already seen that mapped name in the same year on IBJJF.
    """
    ibjjf_ids = set()
    ibjjf_name_year = set()
    for link in ibjjf_links:
        cid = extract_championship_id(link["url"])
        if cid:
            ibjjf_ids.add(cid)
        ibjjf_name_year.add((normalize(link["tournament"]), link["year"]))

    kept_cbjj = []
    dropped = 0
    for link in cbjj_links:
        cid = extract_championship_id(link["url"])
        if cid and cid in ibjjf_ids:
            dropped += 1
            continue
        candidate_names = [link["tournament"]]
        mapped = CBJJ_NAME_MAP.get(link["tournament"])
        if mapped:
            candidate_names.append(mapped)
        if any(
            (normalize(name), link["year"]) in ibjjf_name_year
            for name in candidate_names
        ):
            dropped += 1
            continue
        kept_cbjj.append(link)

    print(
        f"De-dup: kept {len(kept_cbjj)}/{len(cbjj_links)} CBJJ links "
        f"({dropped} dropped as duplicates of IBJJF events)",
        file=sys.stderr,
    )
    return ibjjf_links + kept_cbjj


# ---------------------------------------------------------------------------
# Division parsing (athlete sections only).
# ---------------------------------------------------------------------------


WEIGHT_PAREN_RE = re.compile(r"\s+\(.*\)\s*$")


def parse_division(name):
    """Parse 'BELT / AGE / GENDER / WEIGHT' (in any order). Returns None on failure."""
    cleaned = WEIGHT_PAREN_RE.sub("", name).strip()
    parts = [p.strip() for p in cleaned.split("/")]
    if len(parts) < 4:
        return None

    age = belt = weight = gender = None
    for part in parts:
        if age is None:
            try:
                age = translate_age_keep_juvenile(part)
                continue
            except ValueError:
                pass
        if belt is None:
            try:
                belt = translate_belt(part.upper())
                continue
            except ValueError:
                pass
        if weight is None:
            try:
                weight = translate_weight(part)
                continue
            except ValueError:
                pass
        if gender is None:
            try:
                gender = translate_gender(part)
                continue
            except ValueError:
                pass
    if not (age and belt and weight and gender):
        return None
    return f"{belt} / {age} / {gender} / {weight}"


# ---------------------------------------------------------------------------
# New-format parser (ibjjfdb.com).
# ---------------------------------------------------------------------------


def parse_new_format(html):
    """Yield (division, athlete_name, team_name, place) tuples from a new-format page."""
    soup = BeautifulSoup(html, "html.parser")
    for subtitle in soup.find_all("h4", class_="subtitle"):
        division_text = subtitle.get_text(" ", strip=True)
        division = parse_division(division_text)
        if not division:
            continue

        list_div = subtitle.find_next_sibling("div", class_="list")
        if not list_div:
            continue

        for item in list_div.find_all("div", class_="athlete-item"):
            position = item.find("div", class_="position-athlete")
            place = position.get_text(strip=True) if position else ""

            name_div = item.find("div", class_="name")
            athlete = team = ""
            if name_div:
                p_tag = name_div.find("p")
                if p_tag:
                    span = p_tag.find("span")
                    team = span.get_text(strip=True) if span else ""
                    # athlete name = p text minus the span text
                    if span:
                        span.extract()
                    athlete = p_tag.get_text(strip=True)
            if not place or not athlete:
                continue
            yield division, athlete, team, place


# ---------------------------------------------------------------------------
# Old-format parser (pre-2012 ibjjf.com and cbjj.com.br).
# ---------------------------------------------------------------------------


def parse_old_format(html):
    """Yield (division, athlete_name, team_name, place) tuples from a pre-2012 page.

    The page has two sections: 'Results of academies' (single-field
    'Adult Male' etc. headers) and 'athletes results by category' (full
    BELT/AGE/GENDER/WEIGHT headers). We only want the latter; we filter
    by requiring a parseable division and an athlete-academy cell.
    """
    soup = BeautifulSoup(html, "html.parser")

    # The athletes-by-category section lives inside <div class="col-sm-12 athletes">.
    # Restrict to that scope if present; otherwise fall back to scanning the whole
    # document and rely on parse_division rejecting academy-section headers.
    athletes_section = soup.find("div", class_="athletes") or soup

    for cat in athletes_section.find_all("div", class_="category"):
        division_text = cat.get_text(" ", strip=True)
        division = parse_division(division_text)
        if not division:
            continue

        table = cat.find_next_sibling("table")
        if not table:
            continue

        for row in table.find_all("tr"):
            place_td = row.find("td", class_="place")
            cell = row.find("td", class_="athlete-academy")
            if not (place_td and cell):
                continue
            place = place_td.get_text(strip=True)
            name_div = cell.find("div", class_="athlete-name")
            team_div = cell.find("div", class_="academy-name")
            athlete = name_div.get_text(strip=True) if name_div else ""
            team = team_div.get_text(strip=True) if team_div else ""
            if not place or not athlete:
                continue
            yield division, athlete, team, place


# ---------------------------------------------------------------------------
# Per-event-year dispatch.
# ---------------------------------------------------------------------------


def parse_result_page(url, html):
    host = urlparse(url).netloc.lower()
    if "ibjjfdb.com" in host:
        rows = parse_new_format(html)
    else:
        # Old IBJJF (ibjjf.com), CBJJ (cbjj.com.br, www.cbjj.com.br), and the legacy
        # Heroku staging URLs all share the same pre-2012 markup.
        rows = parse_old_format(html)

    # The CBJJ pre-2012 pages have a quirk where the same athlete row is repeated
    # many times when there's only one competitor in a division. Drop exact
    # duplicates within a single event.
    seen = set()
    out = []
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Top-level orchestration.
# ---------------------------------------------------------------------------


def log_stderr(message):
    print(message, file=sys.stderr)


def build_result_links(
    source="all",
    year=None,
    tournament=None,
    limit=None,
    session=None,
    log=log_stderr,
):
    """Return result-page links after source/year/tournament filtering."""
    session = session or make_session()

    sources_to_fetch = ["ibjjf", "cbjj"] if source == "all" else [source]

    all_links = []
    ibjjf_links = []
    cbjj_links = []
    if "ibjjf" in sources_to_fetch:
        log(f"Fetching IBJJF index {IBJJF_RESULTS_URL} ...")
        ibjjf_links = parse_index_page(fetch(IBJJF_RESULTS_URL, session), "ibjjf")
        log(f"  found {len(ibjjf_links)} event-year links")
        ibjjf_links.extend(EXTRA_IBJJF_LINKS)
        log(f"  added {len(EXTRA_IBJJF_LINKS)} extra hard-coded IBJJF links")
    if "cbjj" in sources_to_fetch:
        log(f"Fetching CBJJ index {CBJJ_RESULTS_URL} ...")
        cbjj_links = parse_index_page(fetch(CBJJ_RESULTS_URL, session), "cbjj")
        log(f"  found {len(cbjj_links)} event-year links")

    if "ibjjf" in sources_to_fetch and "cbjj" in sources_to_fetch:
        all_links = dedup_links(ibjjf_links, cbjj_links)
    else:
        all_links = ibjjf_links + cbjj_links

    # IBJJF's index page occasionally lists two different event-year entries
    # pointing to the same destination URL — typically a Kids/regional event
    # accidentally linked to an Adult/main championship's results page. The
    # old behaviour ("keep first, warn") silently mis-labelled real medal
    # data when the wrong label happened to come first in the index.
    #
    # New behaviour:
    #   1. Drop any index entry listed in KNOWN_BAD_LINKS — explicit allowlist
    #      of label/championship-id pairs we've confirmed are mislabeled.
    #   2. After that, identical-label re-listings (same tournament+year at
    #      the same URL) are dropped silently as harmless duplicates.
    #   3. Any remaining URL collision between distinct labels aborts the
    #      scrape so a human can investigate and either get IBJJF to fix
    #      the link or add the bad entry to KNOWN_BAD_LINKS.
    filtered = []
    skipped_known_bad = 0
    for link in all_links:
        cid = extract_championship_id(link["url"])
        if cid and (link["tournament"], link["year"], cid) in KNOWN_BAD_LINKS:
            log(
                f"NOTICE: skipping known-mislabeled IBJJF index entry: "
                f"'{link['tournament']} {link['year']}' -> {link['url']}"
            )
            skipped_known_bad += 1
            continue
        filtered.append(link)
    if skipped_known_bad:
        log(f"KNOWN_BAD_LINKS: skipped {skipped_known_bad} entries")
    all_links = filtered

    deduped = []
    seen_urls = {}
    for link in all_links:
        prev = seen_urls.get(link["url"])
        if prev is None:
            seen_urls[link["url"]] = link
            deduped.append(link)
            continue
        if (prev["tournament"], prev["year"]) == (link["tournament"], link["year"]):
            # Same tournament+year listed twice with identical URL — benign.
            continue
        raise SystemExit(
            f"ERROR: URL appears in the IBJJF index under multiple distinct "
            f"tournament labels — refusing to silently pick one.\n"
            f"  URL: {link['url']}\n"
            f"  Label A: '{prev['tournament']} {prev['year']}' ({prev['source']})\n"
            f"  Label B: '{link['tournament']} {link['year']}' ({link['source']})\n"
            f"Resolve by adding the mislabeled (tournament, championship_id) "
            f"pair to KNOWN_BAD_LINKS in get_medals.py."
        )
    all_links = deduped

    if year:
        all_links = [link for link in all_links if link["year"] == str(year)]
        log(f"Filtered to year={year}: {len(all_links)} links")

    if tournament:
        needle = tournament.lower()
        all_links = [link for link in all_links if needle in link["tournament"].lower()]
        log(f"Filtered to tournament~='{tournament}': {len(all_links)} links")

    if limit:
        all_links = all_links[:limit]

    return all_links


def default_scraped_at():
    # One scraped_at value for the whole run, so all rows from this scrape sort
    # together and `MAX(scraped_at)` in the admin UI shows the last scrape time.
    # Naive UTC ISO timestamp matches the table's `DateTime` (no tz) column.
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()


def iter_result_medal_rows(
    links,
    session=None,
    scraped_at=None,
    stats=None,
    delay_seconds=REQUEST_DELAY_SECONDS,
    log=log_stderr,
):
    """Yield result_medals-shaped row dicts for already-enumerated links."""
    session = session or make_session()
    scraped_at = scraped_at or default_scraped_at()
    if stats is None:
        stats = {}
    stats.update(
        {
            "total_rows": 0,
            "ok_events": 0,
            "failed_events": 0,
            "empty_events": 0,
            "events": len(links),
        }
    )

    for i, link in enumerate(links, 1):
        event_name = f"{link['tournament']} {link['year']}"
        url = link["url"]
        championship_id = extract_championship_id(url) or ""

        log(f"[{i}/{len(links)}] {link['source']} {event_name} -> {url}")

        try:
            html = fetch(url, session)
        except requests.RequestException as exc:
            log(f"  ! fetch failed: {exc}")
            stats["failed_events"] += 1
            time.sleep(delay_seconds)
            continue

        try:
            rows = parse_result_page(url, html)
        except Exception as exc:  # noqa: BLE001
            log(f"  ! parse failed: {exc}")
            stats["failed_events"] += 1
            time.sleep(delay_seconds)
            continue

        if not rows:
            stats["empty_events"] += 1
        else:
            stats["ok_events"] += 1

        for division, athlete, team, place in rows:
            row = {
                "event_name": event_name,
                "event_ibjjf_id": championship_id,
                "division": division,
                "athlete_name": athlete,
                "team_name": team,
                "place": place,
                "source": link["source"],
                "event_url": url,
                "scraped_at": scraped_at,
            }
            row["id"] = str(deterministic_id(row))
            stats["total_rows"] += 1
            yield row

        time.sleep(delay_seconds)


def scrape(args):
    session = make_session()
    all_links = build_result_links(
        source=args.source,
        year=args.year,
        tournament=args.tournament,
        limit=args.limit,
        session=session,
    )

    # Column order matches the result_medals table so `\copy ... FROM file CSV HEADER`
    # loads without an explicit column list.
    fieldnames = [
        "id",
        "event_name",
        "event_ibjjf_id",
        "division",
        "athlete_name",
        "team_name",
        "place",
        "source",
        "event_url",
        "scraped_at",
    ]
    scraped_at = default_scraped_at()

    with open(args.output, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()

        stats = {}
        for row in iter_result_medal_rows(
            all_links, session=session, scraped_at=scraped_at, stats=stats
        ):
            writer.writerow(row)

    print(
        f"\nDone: {stats['ok_events']} events with rows, "
        f"{stats['empty_events']} empty, {stats['failed_events']} failed. "
        f"Wrote {stats['total_rows']} rows to {args.output}.",
        file=sys.stderr,
    )


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        "-o",
        default="medals.csv",
        help="Output CSV path (default: medals.csv).",
    )
    parser.add_argument(
        "--source",
        choices=["all", "ibjjf", "cbjj"],
        default="all",
        help="Which result index(es) to scrape (default: all).",
    )
    parser.add_argument(
        "--year",
        help="Only scrape this 4-digit year (useful for testing).",
    )
    parser.add_argument(
        "--tournament",
        help="Only scrape event-years whose tournament name contains this substring (case-insensitive).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Stop after this many event-year pages (useful for testing).",
    )
    return parser.parse_args()


def main():
    scrape(parse_args())


if __name__ == "__main__":
    main()
