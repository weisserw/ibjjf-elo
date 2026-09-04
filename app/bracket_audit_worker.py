"""Database-backed worker for live bracket seeding and layout audits."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from bracket_audit import (
    compare_criteria,
    compare_layout,
    first_round_slots_from_matches,
    parse_bracket_competitors,
    parse_official_ranking,
    parse_team_swaps,
    reconcile_competitors,
)
from constants import (
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
    OPEN_CLASS_LIGHT,
    translate_age_keep_juvenile,
    translate_belt,
    translate_gender,
    translate_weight,
)
from extensions import db
from models import BracketAuditCategory, BracketAuditRun, BracketPage, RegistrationLink
from pull import parse_categories
from routes.brackets import (
    build_registration_prediction,
    format_division,
    get_bracket_page,
    parse_match,
)


BASE_URL = "https://www.bjjcompsystem.com"
CATEGORY_ID_RE = re.compile(r"/categories/(\d+)")
AUDIT_AGES = {
    ADULT,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_6,
    MASTER_7,
}
OPEN_CLASS_WEIGHTS = {OPEN_CLASS, OPEN_CLASS_LIGHT, OPEN_CLASS_HEAVY}


def _category_status(categories):
    included = [row for row in categories if row.status != "skipped"]
    statuses = [row.status for row in included]
    return {
        "total": len(included),
        "processed": sum(status in {"complete", "error"} for status in statuses),
        "errors": statuses.count("error"),
        "clean": sum(
            row.status == "complete"
            and row.criteria_status == "match"
            and row.layout_status == "exact"
            for row in included
        ),
        "criteria": sum(row.criteria_status == "criteria_mismatch" for row in included),
        "tie": sum(row.criteria_status == "tie_order_only" for row in included),
        "layout": sum(
            row.layout_status in {"pairing_mismatch", "seed_coverage_mismatch"}
            for row in included
        ),
        "missing": sum(row.ranking_status == "absent" for row in included),
        "unresolved": sum(
            row.criteria_status in {"identity_mismatch", "unverifiable"}
            for row in included
        ),
    }


def _update_run_counts(run):
    counts = _category_status(run.categories)
    run.total_category_count = counts["total"]
    run.processed_category_count = counts["processed"]
    run.error_category_count = counts["errors"]
    run.clean_category_count = counts["clean"]
    run.criteria_mismatch_count = counts["criteria"]
    run.tie_only_count = counts["tie"]
    run.layout_mismatch_count = counts["layout"]
    run.missing_table_count = counts["missing"]
    run.unresolved_category_count = counts["unresolved"]


def discover_categories(run):
    seen = set()
    included_count = 0
    for index_url, raw_gender in (
        (f"{BASE_URL}/tournaments/{run.tournament_id}/categories?locale=en", "Male"),
        (
            f"{BASE_URL}/tournaments/{run.tournament_id}/categories?gender_id=2&locale=en",
            "Female",
        ),
    ):
        html = get_bracket_page(index_url, datetime.now() - timedelta(minutes=10))
        for raw in parse_categories(BeautifulSoup(html, "html.parser")):
            category_url = urljoin(BASE_URL, raw["link"])
            if category_url in seen:
                continue
            seen.add(category_url)
            match = CATEGORY_ID_RE.search(category_url)
            category = BracketAuditCategory(
                run=run,
                external_category_id=match.group(1) if match else None,
                category_url=category_url,
                raw_gender=raw_gender,
                raw_age=raw.get("age"),
                raw_belt=raw.get("belt"),
                raw_weight=raw.get("weight"),
                status="pending",
            )
            try:
                category.age = translate_age_keep_juvenile(raw["age"])
            except ValueError as exc:
                category.status = "skipped"
                category.error_text = str(exc)
            if category.status != "skipped" and category.age not in AUDIT_AGES:
                category.status = "skipped"
            if category.status != "skipped":
                try:
                    category.gender = translate_gender(raw_gender)
                    category.belt = translate_belt(raw["belt"])
                    category.weight = translate_weight(raw["weight"])
                except ValueError as exc:
                    category.status = "error"
                    category.error_text = str(exc)
            if category.status != "skipped" and category.weight in OPEN_CLASS_WEIGHTS:
                category.status = "skipped"
            if category.status != "skipped":
                included_count += 1
            db.session.add(category)

    run.discovered_category_count = len(seen)
    run.total_category_count = included_count
    db.session.commit()


def _reconciliation_status(reconciled):
    statuses = {row["status"] for row in reconciled}
    if statuses <= {"matched"}:
        return "matched"
    for status in (
        "ambiguous",
        "unresolved",
        "registration_missing",
        "official_missing",
    ):
        if status in statuses:
            return status
    return "unresolved"


def process_category(run, category, registration_link):
    category.status = "running"
    db.session.commit()

    html = get_bracket_page(
        category.category_url, datetime.now() - timedelta(minutes=10)
    )
    page = (
        BracketPage.query.filter_by(link=category.category_url)
        .order_by(BracketPage.saved_at.desc())
        .first()
    )
    category.cache_saved_at = page.saved_at if page else None

    live_rows = parse_bracket_competitors(html)
    if len(live_rows) < 4:
        category.status = "skipped"
        category.official_competitor_count = len(live_rows)
        return

    ranking = parse_official_ranking(html)
    division = format_division(
        {
            "belt": category.belt,
            "age": category.age,
            "gender": category.gender,
            "weight": category.weight,
        }
    )
    prediction, provenance = build_registration_prediction(
        registration_link.link,
        division,
        run.gi,
        now=run.started_at or run.created_at,
        registration_link_record=registration_link,
    )
    predicted_rows = prediction["competitors"]

    reconciled = reconcile_competitors(ranking["rows"], live_rows, predicted_rows)
    if ranking["status"] == "parsed":
        criteria = compare_criteria(
            reconciled,
            ranking["variant"],
            [
                field
                for row in ranking["rows"]
                for field in row.get("criteria", {}).keys()
            ],
        )
    else:
        criteria = {
            "status": "unverifiable",
            "rows": reconciled,
            "matched_count": 0,
            "mismatched_count": 0,
            "unresolved_count": len(reconciled),
            "differing_field_count": 0,
        }

    try:
        soup = BeautifulSoup(html, "html.parser")
        match_nodes = soup.find_all("div", class_="tournament-category__match")
        parsed_matches = [parse_match(match, category.weight) for match in match_nodes]
        failed_match_count = sum(match is None for match in parsed_matches)
        if not match_nodes:
            raise ValueError("Live bracket parser found no matches")
        if failed_match_count:
            raise ValueError(
                "Live bracket parser could not parse "
                f"{failed_match_count} of {len(match_nodes)} matches"
            )
        parsed_layout = first_round_slots_from_matches(
            parsed_matches, parse_team_swaps(soup)
        )
        layout_count = (
            ranking["official_competitor_count"]
            if ranking["status"] == "parsed"
            else len(live_rows)
        )
        layout = compare_layout(parsed_layout, layout_count or None)
    except (TypeError, ValueError) as exc:
        parsed_layout = None
        layout = {"status": "unverifiable", "reason": str(exc)}

    category.seeding_variant = ranking["variant"]
    category.normalized_headers_json = json.dumps(ranking.get("normalized_headers", []))
    category.unmapped_headers_json = json.dumps(ranking["unmapped_headers"])
    category.official_competitor_count = ranking["official_competitor_count"] or len(
        live_rows
    )
    category.parsed_bracket_size = (
        parsed_layout["bracket_size"] if parsed_layout is not None else None
    )
    category.theoretical_bracket_size = layout.get("theoretical_bracket_size")
    category.ranking_status = ranking["status"]
    category.reconciliation_status = _reconciliation_status(reconciled)
    category.criteria_status = criteria["status"]
    category.layout_status = layout["status"]
    category.matched_competitor_count = criteria["matched_count"]
    category.mismatched_competitor_count = criteria["mismatched_count"]
    category.unresolved_row_count = criteria["unresolved_count"]
    category.differing_criteria_count = criteria["differing_field_count"]
    category.report = {
        "ranking": ranking,
        "live_competitors": live_rows,
        "prediction": prediction,
        "prediction_provenance": provenance,
        "reconciliation": reconciled,
        "criteria": criteria,
        "layout": layout,
    }
    category.status = "complete"


def run_bracket_audit(run_id, sleep=time.sleep):
    run = db.session.get(BracketAuditRun, run_id)
    if run is None:
        raise ValueError(f"Bracket audit run {run_id} does not exist")
    registration_link = db.session.get(RegistrationLink, run.registration_link_id)
    if registration_link is None:
        raise ValueError("The selected registration source no longer exists")

    run.status = "running"
    run.started_at = datetime.utcnow()
    run.registration_source_at = registration_link.updated_at
    run.medal_cutoff = registration_link.event_start_date
    run.seeding_reference_date = (
        min(run.started_at, registration_link.event_start_date)
        if registration_link.event_start_date
        else run.started_at
    )
    db.session.commit()

    try:
        discover_categories(run)
    except Exception as exc:
        db.session.rollback()
        run = db.session.get(BracketAuditRun, run_id)
        run.status = "error"
        run.fatal_error = str(exc)
        run.finished_at = datetime.utcnow()
        db.session.commit()
        raise

    categories = (
        BracketAuditCategory.query.filter_by(run_id=run.id)
        .order_by(BracketAuditCategory.category_url)
        .all()
    )
    for index, category in enumerate(categories):
        if category.status in {"error", "skipped"}:
            _update_run_counts(run)
            db.session.commit()
            continue
        try:
            process_category(run, category, registration_link)
            if category.status == "skipped":
                print(
                    f"[{index + 1}/{len(categories)}] {category.category_url}: "
                    "skipped (fewer than 4 athletes)",
                    flush=True,
                )
            else:
                print(
                    f"[{index + 1}/{len(categories)}] {category.category_url}: "
                    f"criteria={category.criteria_status} layout={category.layout_status}",
                    flush=True,
                )
        except Exception as exc:
            db.session.rollback()
            category = db.session.get(BracketAuditCategory, category.id)
            category.status = "error"
            category.error_text = str(exc)
            print(
                f"[{index + 1}/{run.total_category_count}] {category.category_url}: error: {exc}",
                flush=True,
            )
        run = db.session.get(BracketAuditRun, run_id)
        _update_run_counts(run)
        db.session.commit()
        if index + 1 < len(categories):
            sleep(0.5)

    _update_run_counts(run)
    run.status = "partial" if run.error_category_count else "complete"
    run.finished_at = datetime.utcnow()
    db.session.commit()
    return run
