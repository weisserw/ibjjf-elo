#!/usr/bin/env python3
"""Scrape 2013+ IBJJF/CBJJ results into separate, resumable audit files.

This script does not connect to the application database. Each event is written
atomically to --output-dir/events; a rerun skips successful event files.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import get_medals  # noqa: E402


FIELDS = [
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
THREAD_LOCAL = threading.local()
SCRAPER_VERSION = "2"


def write_json(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def scrape_event(link, csv_path, metadata_path, delay):
    if not hasattr(THREAD_LOCAL, "session"):
        THREAD_LOCAL.session = get_medals.make_session()
    championship_id = get_medals.extract_championship_id(link["url"])
    try:
        html = get_medals.fetch(link["url"], THREAD_LOCAL.session)
        parsed = get_medals.parse_result_page(link["url"], html)
        scraped_at = get_medals.default_scraped_at()
        event_name = f"{link['tournament']} {link['year']}"
        rows = []
        for division, athlete, team, place in parsed:
            row = {
                "event_name": event_name,
                "event_ibjjf_id": championship_id or "",
                "division": division,
                "athlete_name": athlete,
                "team_name": team,
                "place": place,
                "source": link["source"],
                "event_url": link["url"],
                "scraped_at": scraped_at,
            }
            row["id"] = str(get_medals.deterministic_id(row))
            rows.append(row)
        tmp = csv_path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(tmp, csv_path)
        csv_sha256 = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        write_json(
            metadata_path,
            {
                "source": link["source"],
                "year": link["year"],
                "championship_id": championship_id,
                "event_name": event_name,
                "url": link["url"],
                "scraped_at": scraped_at,
                "rows": len(rows),
                "status": "success" if rows else "unexpected_empty",
                "sha256": csv_sha256,
                "scraper_version": SCRAPER_VERSION,
            },
        )
        return {"rows": len(rows)}
    except Exception as exc:  # noqa: BLE001 - independent pages can continue
        return {"error": str(exc), "url": link["url"]}
    finally:
        time.sleep(max(0, delay))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-year", type=int, default=2013)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.min_year < 2013:
        parser.error("This audit excludes events before 2013")
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")

    root = args.output_dir
    event_dir = root / "events"
    event_dir.mkdir(parents=True, exist_ok=True)
    session = get_medals.make_session()
    links = get_medals.build_result_links(source="all", session=session)
    links = [
        link
        for link in links
        if link["year"].isdigit() and int(link["year"]) >= args.min_year
    ]
    run_started = datetime.now(timezone.utc).isoformat()
    write_json(root / "index.json", {"started_at_utc": run_started, "links": links})
    print(f"Queued {len(links)} in-scope event pages", flush=True)

    counts = {"success": 0, "empty": 0, "failed": 0, "skipped": 0, "rows": 0}
    failures = []
    pending = []
    for position, link in enumerate(links, 1):
        championship_id = get_medals.extract_championship_id(link["url"])
        stable_id = (
            championship_id
            or hashlib.sha1(link["url"].encode("utf-8")).hexdigest()[:12]
        )
        key = f"{link['source']}_{stable_id}_{link['year']}"
        csv_path = event_dir / f"{key}.csv"
        metadata_path = event_dir / f"{key}.json"
        if csv_path.exists() and metadata_path.exists():
            counts["skipped"] += 1
            counts["rows"] += json.loads(metadata_path.read_text(encoding="utf-8"))[
                "rows"
            ]
            continue
        pending.append((link, csv_path, metadata_path))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(scrape_event, link, csv_path, metadata_path, args.delay): link
            for link, csv_path, metadata_path in pending
        }
        for completed, future in enumerate(as_completed(futures), 1):
            result = future.result()
            if "error" in result:
                counts["failed"] += 1
                failures.append(result)
                print(f"FAILED {result['url']}: {result['error']}", flush=True)
            else:
                counts["success" if result["rows"] else "empty"] += 1
                counts["rows"] += result["rows"]
            position = counts["skipped"] + completed
            if position % 50 == 0 or completed == len(pending):
                write_json(
                    root / "progress.json",
                    {
                        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                        "position": position,
                        "total": len(links),
                        "counts": counts,
                        "failures": failures,
                    },
                )
                print(f"{position}/{len(links)} {counts}", flush=True)

    write_json(
        root / "progress.json",
        {
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "position": len(links),
            "total": len(links),
            "counts": counts,
            "failures": failures,
        },
    )
    write_json(
        root / "manifest.json",
        {
            "started_at_utc": run_started,
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "scraper_version": SCRAPER_VERSION,
            "status": (
                "complete"
                if not counts["failed"] and not counts["empty"]
                else "incomplete"
            ),
            "counts": counts,
            "events": [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(event_dir.glob("*.json"))
            ],
        },
    )
    print("Finished", counts, flush=True)


if __name__ == "__main__":
    main()
