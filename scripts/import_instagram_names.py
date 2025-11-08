#!/usr/bin/env python

import sys
import os
import csv
from uuid import UUID

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import db, app
from models import Athlete


def to_null(val):
    return val if val and val.strip() else None


def coalesce(arg, default):
    return arg if arg is not None else default


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: import_instagram_names.py <instagram_names.csv>")
        sys.exit(1)
    csv_path = sys.argv[1]
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        with app.app_context():
            for row in reader:
                id = row["id"].strip()
                personal_name = to_null(row.get("personal_name", ""))
                athlete = db.session.get(Athlete, UUID(id))
                if not athlete:
                    print(f"No athlete found for id: {id}")
                    continue
                if coalesce(personal_name, "") != coalesce(athlete.personal_name, ""):
                    athlete.personal_name = personal_name
                    print(
                        f"Updated {id} / {athlete.name}: personal_name={personal_name}"
                    )
            db.session.commit()
    print("Import complete.")
