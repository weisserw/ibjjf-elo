#!/usr/bin/env python3

import argparse
import csv
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import psycopg2.extras

sys.path.append(str(Path(__file__).resolve().parent.parent / "app"))
from constants import (
    translate_age,
    translate_belt,
    translate_gender,
    translate_weight,
)  # noqa: E402
from normalize import normalize  # noqa: E402

FIXED_ATHLETE_ID = "d19a56b7-b59a-4c6e-bf76-1b4818555762"


def parse_args():
    parser = argparse.ArgumentParser(description="One-off medals CSV importer.")
    parser.add_argument(
        "--csv",
        default="medals.csv",
        help="Path to medals CSV (default: medals.csv).",
    )
    parser.add_argument(
        "--database-url-file",
        default="DATABASE_URL",
        help="File containing the Postgres DATABASE_URL (default: DATABASE_URL).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print report without inserting rows.",
    )
    return parser.parse_args()


def read_database_url(path):
    return Path(path).read_text(encoding="utf-8").strip()


def load_rows(csv_path):
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) < 6:
                raise ValueError(
                    f"Row {line_number} has {len(row)} columns; expected at least 6."
                )
            rows.append(
                {
                    "line_number": line_number,
                    "event_name": row[0].strip(),
                    "event_ibjjf_id": row[1].strip(),
                    "division_text": row[2].strip(),
                    "athlete_name": row[3].strip(),
                    "team_name": row[4].strip(),
                    "place": row[5].strip(),
                }
            )
    return rows


def fetch_event_maps(conn, event_names, event_ibjjf_ids, normalized_names):
    ibjjf_map = defaultdict(list)
    name_map = defaultdict(list)
    normalized_map = defaultdict(list)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if event_ibjjf_ids:
            cur.execute(
                """
                SELECT id, ibjjf_id, name, normalized_name
                FROM events
                WHERE ibjjf_id = ANY(%s)
                """,
                (event_ibjjf_ids,),
            )
            for record in cur.fetchall():
                ibjjf_map[record["ibjjf_id"]].append(record)

        if event_names:
            cur.execute(
                """
                SELECT id, ibjjf_id, name, normalized_name
                FROM events
                WHERE name = ANY(%s)
                """,
                (event_names,),
            )
            for record in cur.fetchall():
                name_map[record["name"]].append(record)

        if normalized_names:
            cur.execute(
                """
                SELECT id, ibjjf_id, name, normalized_name
                FROM events
                WHERE normalized_name = ANY(%s)
                """,
                (normalized_names,),
            )
            for record in cur.fetchall():
                normalized_map[record["normalized_name"]].append(record)

    return ibjjf_map, name_map, normalized_map


def resolve_event(row, ibjjf_map, name_map, normalized_map):
    ibjjf_id = row["event_ibjjf_id"]
    event_name = row["event_name"]
    normalized_name = normalize(event_name)

    if ibjjf_id and ibjjf_id in ibjjf_map:
        matches = ibjjf_map[ibjjf_id]
        if len(matches) == 1:
            return ("resolved", matches[0], "ibjjf_id")
        return ("ambiguous", matches, "ibjjf_id")

    if event_name in name_map:
        matches = name_map[event_name]
        if len(matches) == 1:
            return ("resolved", matches[0], "name")
        return ("ambiguous", matches, "name")

    if normalized_name in normalized_map:
        matches = normalized_map[normalized_name]
        if len(matches) == 1:
            return ("resolved", matches[0], "normalized_name")
        return ("ambiguous", matches, "normalized_name")

    return ("missing", None, None)


def parse_division(division_text):
    parts = [part.strip() for part in division_text.split("/")]
    if len(parts) != 4:
        raise ValueError(
            f"Invalid division format '{division_text}'. Expected: BELT / AGE / GENDER / WEIGHT"
        )

    belt = translate_belt(parts[0])
    age = translate_age(parts[1])
    gender = translate_gender(parts[2])
    weight = translate_weight(parts[3])

    return belt, age, gender, weight


def extract_year(event_name):
    match = re.search(r"(\d{4})\s*$", event_name)
    if not match:
        raise ValueError(
            f"Could not parse year from event name '{event_name}'. Expected trailing 4-digit year."
        )
    return int(match.group(1))


def fetch_team_maps(conn, team_names):
    exact_map = defaultdict(list)
    normalized_map = defaultdict(list)

    if not team_names:
        return exact_map, normalized_map

    normalized_names = sorted({normalize(name) for name in team_names})
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, name, normalized_name
            FROM teams
            WHERE name = ANY(%s)
               OR normalized_name = ANY(%s)
            """,
            (team_names, normalized_names),
        )
        for record in cur.fetchall():
            exact_map[record["name"]].append(record)
            normalized_map[record["normalized_name"]].append(record)

    return exact_map, normalized_map


def resolve_team(row, team_name_map, team_normalized_map):
    team_name = row["team_name"]
    if team_name in team_name_map:
        matches = team_name_map[team_name]
        if len(matches) == 1:
            return ("resolved", matches[0], "name")
        return ("ambiguous", matches, "name")

    normalized_name = normalize(team_name)
    if normalized_name in team_normalized_map:
        matches = team_normalized_map[normalized_name]
        if len(matches) == 1:
            return ("resolved", matches[0], "normalized_name")
        return ("ambiguous", matches, "normalized_name")

    return ("missing", None, None)


def fetch_division_maps(conn, divisions):
    division_map = defaultdict(list)
    if not divisions:
        return division_map

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, belt, age, gender, weight, gi
            FROM divisions
            """
        )
        for record in cur.fetchall():
            key = (
                record["belt"],
                record["age"],
                record["gender"],
                record["weight"],
                record["gi"],
            )
            division_map[key].append(record)

    return division_map


def print_preflight_report(
    rows,
    event_resolutions,
    missing_events,
    ambiguous_events,
    missing_teams,
    ambiguous_teams,
    missing_divisions,
    ambiguous_divisions,
):
    print(f"Rows scanned: {len(rows)}")
    print(f"Rows resolved to events: {len(event_resolutions)}")
    print(f"Rows with missing events: {len(missing_events)}")
    print(f"Rows with ambiguous events: {len(ambiguous_events)}")
    print(f"Rows with missing teams: {len(missing_teams)}")
    print(f"Rows with ambiguous teams: {len(ambiguous_teams)}")
    print(f"Rows with missing divisions: {len(missing_divisions)}")
    print(f"Rows with ambiguous divisions: {len(ambiguous_divisions)}")

    if missing_events:
        print("\nMissing events")
        counts = defaultdict(int)
        first_line = {}
        for row in missing_events:
            key = (row["event_name"], row["event_ibjjf_id"])
            counts[key] += 1
            if key not in first_line:
                first_line[key] = row["line_number"]
        for (event_name, ibjjf_id), count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0][0])
        ):
            print(
                f"  lines~{first_line[(event_name, ibjjf_id)]}: "
                f"event='{event_name}' ibjjf_id='{ibjjf_id or '(blank)'}' "
                f"rows={count}"
            )

    if ambiguous_events:
        print("\nAmbiguous event matches")
        for row, matches, via in ambiguous_events[:20]:
            print(
                f"  line {row['line_number']}: event='{row['event_name']}' "
                f"ibjjf_id='{row['event_ibjjf_id'] or '(blank)'}' via {via}"
            )
            for match in matches:
                print(
                    f"    - id={match['id']} ibjjf_id={match['ibjjf_id']} "
                    f"name={match['name']}"
                )
        if len(ambiguous_events) > 20:
            print(f"  ... and {len(ambiguous_events) - 20} more ambiguous rows")

    if missing_teams:
        print("\nMissing teams")
        counts = defaultdict(int)
        first_line = {}
        for row in missing_teams:
            key = row["team_name"]
            counts[key] += 1
            if key not in first_line:
                first_line[key] = row["line_number"]
        for team_name, count in sorted(
            counts.items(), key=lambda item: (-item[1], item[0])
        ):
            print(f"  lines~{first_line[team_name]}: team='{team_name}' rows={count}")

    if ambiguous_teams:
        print("\nAmbiguous team matches")
        for row, matches, via in ambiguous_teams[:20]:
            print(f"  line {row['line_number']}: team='{row['team_name']}' via {via}")
            for match in matches:
                print(
                    f"    - id={match['id']} name={match['name']} normalized_name={match['normalized_name']}"
                )
        if len(ambiguous_teams) > 20:
            print(f"  ... and {len(ambiguous_teams) - 20} more ambiguous rows")

    if missing_divisions:
        print("\nMissing divisions")
        for row, key in missing_divisions[:20]:
            print(
                "  line {line}: division='{division}' gi={gi} "
                "(belt='{belt}', age='{age}', gender='{gender}', weight='{weight}')".format(
                    line=row["line_number"],
                    division=row["division_text"],
                    gi=key[4],
                    belt=key[0],
                    age=key[1],
                    gender=key[2],
                    weight=key[3],
                )
            )
        if len(missing_divisions) > 20:
            print(f"  ... and {len(missing_divisions) - 20} more missing division rows")

    if ambiguous_divisions:
        print("\nAmbiguous divisions")
        for row, matches, key in ambiguous_divisions[:20]:
            print(
                "  line {line}: division='{division}' gi={gi} "
                "(belt='{belt}', age='{age}', gender='{gender}', weight='{weight}')".format(
                    line=row["line_number"],
                    division=row["division_text"],
                    gi=key[4],
                    belt=key[0],
                    age=key[1],
                    gender=key[2],
                    weight=key[3],
                )
            )
            for match in matches:
                print(f"    - division_id={match['id']}")
        if len(ambiguous_divisions) > 20:
            print(
                f"  ... and {len(ambiguous_divisions) - 20} more ambiguous division rows"
            )


def check_fixed_athlete(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM athletes WHERE id = %s", (FIXED_ATHLETE_ID,))
        return cur.fetchone() is not None


def insert_medals(conn, insert_rows):
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO medals (
                id, happened_at, event_id, division_id, athlete_id, team_id, place, default_gold
            )
            VALUES %s
            """,
            insert_rows,
            template="(%s,%s,%s,%s,%s,%s,%s,%s)",
        )


def main():
    args = parse_args()

    database_url = read_database_url(args.database_url_file)
    rows = load_rows(args.csv)

    event_names = sorted({row["event_name"] for row in rows})
    event_ibjjf_ids = sorted(
        {row["event_ibjjf_id"] for row in rows if row["event_ibjjf_id"]}
    )
    normalized_names = sorted({normalize(row["event_name"]) for row in rows})
    team_names = sorted({row["team_name"] for row in rows})

    prepared_rows = []

    with psycopg2.connect(database_url) as conn:
        if not check_fixed_athlete(conn):
            print(
                f"Fixed athlete id {FIXED_ATHLETE_ID} was not found in athletes table.",
                file=sys.stderr,
            )
            sys.exit(1)

        ibjjf_map, name_map, normalized_map = fetch_event_maps(
            conn, event_names, event_ibjjf_ids, normalized_names
        )
        team_name_map, team_normalized_map = fetch_team_maps(conn, team_names)

        event_resolutions = []
        missing_events = []
        ambiguous_events = []
        missing_teams = []
        ambiguous_teams = []
        missing_divisions = []
        ambiguous_divisions = []
        parsed_rows = []
        division_keys = set()

        for row in rows:
            event_status, event_payload, event_via = resolve_event(
                row, ibjjf_map, name_map, normalized_map
            )
            if event_status == "resolved":
                event_resolutions.append((row, event_payload["id"], event_via))
            elif event_status == "ambiguous":
                ambiguous_events.append((row, event_payload, event_via))
                continue
            else:
                missing_events.append(row)
                continue

            team_status, team_payload, team_via = resolve_team(
                row, team_name_map, team_normalized_map
            )
            if team_status == "missing":
                missing_teams.append(row)
                continue
            if team_status == "ambiguous":
                ambiguous_teams.append((row, team_payload, team_via))
                continue

            try:
                belt, age, gender, weight = parse_division(row["division_text"])
                year = extract_year(row["event_name"])
                place = int(row["place"])
            except ValueError as exc:
                print(
                    f"Line {row['line_number']} parse error: {exc}",
                    file=sys.stderr,
                )
                sys.exit(1)

            gi = "No-Gi" not in row["event_name"]
            division_key = (belt, age, gender, weight, gi)
            division_keys.add(division_key)

            parsed_rows.append(
                {
                    "row": row,
                    "event_id": str(event_payload["id"]),
                    "team_id": str(team_payload["id"]),
                    "division_key": division_key,
                    "happened_at": datetime(year, 1, 1),
                    "place": place,
                }
            )

        division_map = fetch_division_maps(conn, division_keys)
        for parsed in parsed_rows:
            matches = division_map.get(parsed["division_key"], [])
            if not matches:
                missing_divisions.append((parsed["row"], parsed["division_key"]))
                continue
            if len(matches) > 1:
                ambiguous_divisions.append(
                    (parsed["row"], matches, parsed["division_key"])
                )
                continue
            parsed["division_id"] = str(matches[0]["id"])
            prepared_rows.append(parsed)

        print_preflight_report(
            rows,
            event_resolutions,
            missing_events,
            ambiguous_events,
            missing_teams,
            ambiguous_teams,
            missing_divisions,
            ambiguous_divisions,
        )

        if (
            missing_events
            or ambiguous_events
            or missing_teams
            or ambiguous_teams
            or missing_divisions
            or ambiguous_divisions
        ):
            print(
                "\nAborting without inserts due to preflight errors.", file=sys.stderr
            )
            conn.rollback()
            sys.exit(1)

        insert_values = [
            (
                str(uuid.uuid4()),
                parsed["happened_at"],
                parsed["event_id"],
                parsed["division_id"],
                FIXED_ATHLETE_ID,
                parsed["team_id"],
                parsed["place"],
                False,
            )
            for parsed in prepared_rows
        ]

        if args.dry_run:
            conn.rollback()
            print(f"\nDry run complete: {len(insert_values)} rows would be inserted.")
            return

        insert_medals(conn, insert_values)
        conn.commit()
        print(f"\nInserted {len(insert_values)} rows into medals.")


if __name__ == "__main__":
    main()
