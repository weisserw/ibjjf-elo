#!/usr/bin/env python3
"""Run one persisted live bracket audit."""

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import app  # noqa: E402
from bracket_audit_worker import run_bracket_audit  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=uuid.UUID, required=True)
    args = parser.parse_args()
    with app.app_context():
        run = run_bracket_audit(args.run_id)
        print(
            f"Audit {run.id} finished with status {run.status}: "
            f"{run.processed_category_count}/{run.total_category_count} categories",
            flush=True,
        )


if __name__ == "__main__":
    main()
