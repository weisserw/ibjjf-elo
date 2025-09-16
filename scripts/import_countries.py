#!/usr/bin/env python

import sys
import os
import csv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "app"))

from app import db, app
from models import Athlete


def to_null(val):
    return val if val and val.strip() else None


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: import_countries.py <countries.csv>")
        sys.exit(1)
    csv_path = sys.argv[1]
    with open(csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile)
        with app.app_context():
            for row in reader:
                name = row["athlete_name"].strip()
                country_code = to_null(row.get("country_code", ""))
                country_note = to_null(row.get("Tooltip", ""))
                country_note_pt = to_null(row.get("Portuguese Tooltip", ""))
                athletes = db.session.query(Athlete).filter_by(name=name).all()
                if len(athletes) == 0:
                    print(f"No athlete found for name: {name}")
                    continue
                if len(athletes) > 1:
                    print(f"Multiple athletes found for name: {name}")
                    sys.exit(1)
                athlete = athletes[0]
                athlete.country = country_code
                athlete.country_note = country_note
                athlete.country_note_pt = country_note_pt
                print(
                    f"Updated {name}: country={country_code}, note={country_note}, note_pt={country_note_pt}"
                )
            db.session.commit()
    print("Import complete.")
