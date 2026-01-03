import html
import logging
import os
from flask import Response, send_from_directory, request
from extensions import db
from models import AthleteRating, Athlete
from routes.athletes import get_athlete_data

logger = logging.getLogger("ibjjf")

DEFAULT_SEO_LIMIT = 50
DEFAULT_RANKING_FILTERS = {
    "gender": "Male",
    "age": "Adult",
    "belt": "BLACK",
    "weight": "",
    "gi": True,
}
INDEX_HTML_CACHE = None
SNIPPET_CACHE = {}
SNIPPET_DIR = os.path.join(os.path.dirname(__file__), "seo_snippets")


def load_index_html(static_folder: str):
    """
    Read the built React index.html once so we can inject a simple pre-rendered
    fallback for search engines while still loading the SPA assets.
    """
    global INDEX_HTML_CACHE
    if INDEX_HTML_CACHE:
        return INDEX_HTML_CACHE
    index_path = os.path.join(static_folder, "index.html")
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            INDEX_HTML_CACHE = f.read()
            return INDEX_HTML_CACHE
    except OSError:
        logger.exception("Failed to read index.html from %s", index_path)
        return None


def fetch_default_rankings(limit=DEFAULT_SEO_LIMIT):
    """
    Pull a lightweight snapshot of the default rankings (Adult / Male / Black /
    Gi / P4P) for the SEO placeholder table.
    """
    return (
        db.session.query(
            AthleteRating.rank,
            AthleteRating.rating,
            AthleteRating.match_count,
            Athlete.name,
            Athlete.slug,
            Athlete.country,
        )
        .join(Athlete, AthleteRating.athlete_id == Athlete.id)
        .filter(
            AthleteRating.gender == DEFAULT_RANKING_FILTERS["gender"],
            AthleteRating.age == DEFAULT_RANKING_FILTERS["age"],
            AthleteRating.belt == DEFAULT_RANKING_FILTERS["belt"],
            AthleteRating.gi.is_(DEFAULT_RANKING_FILTERS["gi"]),
            AthleteRating.weight == DEFAULT_RANKING_FILTERS["weight"],
        )
        .order_by(AthleteRating.rank)
        .limit(limit)
        .all()
    )


def build_seo_table_html(rows):
    """
    Render a minimal, static table that mirrors the landing page content so
    crawlers can see meaningful data before the React app mounts.
    """
    table_rows = []
    for row in rows:
        name = html.escape(row.name or "")
        slug = html.escape(row.slug or "")
        country = html.escape(row.country or "")
        rating = f"{round(row.rating):,}" if row.rating is not None else "–"
        matches = row.match_count if row.match_count is not None else "–"
        table_rows.append(
            f"<tr>"
            f"<td>{row.rank}</td>"
            f'<td><a href="/athlete/{slug}">{name}</a></td>'
            f"<td>{country}</td>"
            f"<td>{rating}</td>"
            f"<td>{matches}</td>"
            f"</tr>"
        )

    rows_html = "\n".join(table_rows)
    return f"""
    <section id="seo-fallback" aria-label="IBJJF Adult Male Black Belt P4P Rankings" style="padding:24px;font-family:Arial,Helvetica,sans-serif;">
        <h1 style="font-size:24px;margin:0 0 12px;">IBJJF Adult Male Black Belt P4P Rankings</h1>
        <p style="margin:0 0 16px;font-size:14px;color:#444;">Fast-loading snapshot for search engines. The full interactive table loads immediately after.</p>
        <div style="overflow-x:auto;">
            <table style="width:100%;border-collapse:collapse;">
                <thead>
                    <tr style="text-align:left;border-bottom:1px solid #e0e0e0;">
                        <th style="padding:8px 6px;">Rank</th>
                        <th style="padding:8px 6px;">Athlete</th>
                        <th style="padding:8px 6px;">Country</th>
                        <th style="padding:8px 6px;">Rating</th>
                        <th style="padding:8px 6px;">Matches</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </section>
    """


def render_index_with_fallback(app):
    logger.info("Rendering SEO fallback for path=%s", _safe_request_path())
    base_html = load_index_html(app.static_folder)
    if base_html is None:
        return send_from_directory(app.static_folder, "index.html")

    try:
        rows = fetch_default_rankings()
        fallback_html = build_seo_table_html(rows)
    except Exception:
        logger.exception("Failed to render SEO fallback, serving static index.html")
        return Response(base_html, mimetype="text/html")

    injected_html = base_html.replace(
        '<div id="root"></div>', f'<div id="root">{fallback_html}</div>'
    )
    return Response(injected_html, mimetype="text/html")


def render_index_with_snippet(app, snippet_name: str):
    logger.info(
        "Rendering SEO snippet '%s' for path=%s",
        snippet_name,
        _safe_request_path(),
    )
    base_html = load_index_html(app.static_folder)
    if base_html is None:
        return send_from_directory(app.static_folder, "index.html")

    snippet_html = load_snippet(snippet_name)
    if snippet_html is None:
        logger.warning("SEO snippet '%s' missing, serving static index", snippet_name)
        return Response(base_html, mimetype="text/html")

    injected_html = base_html.replace(
        '<div id="root"></div>', f'<div id="root">{snippet_html}</div>'
    )
    return Response(injected_html, mimetype="text/html")


def render_athlete_page(app, athlete_identifier: str):
    logger.info(
        "Rendering SEO athlete page for %s at path=%s",
        athlete_identifier,
        _safe_request_path(),
    )
    base_html = load_index_html(app.static_folder)
    if base_html is None:
        return send_from_directory(app.static_folder, "index.html")

    try:
        athlete_payload = get_athlete_data(athlete_identifier)
    except Exception:
        logger.exception("Failed to load athlete data for %s", athlete_identifier)
        return Response(base_html, mimetype="text/html")

    if athlete_payload is None:
        return Response(base_html, mimetype="text/html")

    injected_html = base_html.replace(
        '<div id="root"></div>',
        f'<div id="root">{build_athlete_html(athlete_payload)}</div>',
    )
    return Response(injected_html, mimetype="text/html")


def build_athlete_html(payload: dict):
    athlete = payload.get("athlete", {})
    ranks = payload.get("ranks", [])
    medals = payload.get("medals", [])
    registrations = payload.get("registrations", [])

    rank_rows = "".join(
        f"<li>{r.get('gender', '')} / {r.get('age', '')} / {r.get('belt', '')} / {r.get('weight', '')}: Rank {r.get('rank', '')}, Rating {r.get('rating', '')}</li>"
        for r in ranks
    )
    medal_rows = "".join(
        f"<li>{m.get('happened_at', '')}: {m.get('event_name', '')} - {m.get('division', '')} (Place {m.get('place', '')})</li>"
        for m in medals
    )
    reg_rows = "".join(
        f"<li>{reg.get('event_start_date', '')}: {reg.get('event_name', '')} - {reg.get('division', '')}</li>"
        for reg in registrations
    )

    return f"""
    <section id="seo-athlete" style="padding:24px;font-family:Arial,Helvetica,sans-serif;">
        <h1 style="font-size:24px;margin:0 0 12px;">{_esc(athlete.get("name", ""))}</h1>
        <p style="margin:0 0 12px;font-size:14px;color:#444;">
            Rating: {_maybe_number(athlete.get("rating"))} | Belt: {_esc(athlete.get("belt") or "")} | Team: {_esc(athlete.get("team_name") or "")} | Country: {_esc(athlete.get("country") or "")}
        </p>
        <p style="margin:0 0 12px;font-size:14px;color:#444;">Slug: {_esc(athlete.get("slug") or athlete.get("id") or "")}</p>
        <h2 style="font-size:18px;margin:12px 0 6px;">Ranks</h2>
        <ul style="margin:0 0 12px 18px;font-size:14px;">{rank_rows or "<li>No ranks available</li>"}</ul>
        <h2 style="font-size:18px;margin:12px 0 6px;">Registrations</h2>
        <ul style="margin:0 0 12px 18px;font-size:14px;">{reg_rows or "<li>No upcoming registrations</li>"}</ul>
        <h2 style="font-size:18px;margin:12px 0 6px;">Medals</h2>
        <ul style="margin:0 0 12px 18px;font-size:14px;">{medal_rows or "<li>No medals listed</li>"}</ul>
    </section>
    """


def _maybe_number(value):
    if value is None:
        return "N/A"
    try:
        return f"{round(value):,}"
    except Exception:
        return str(value)


def _esc(val: str):
    try:
        return html.escape(val)
    except Exception:
        return ""


def load_snippet(snippet_name: str):
    if snippet_name in SNIPPET_CACHE:
        return SNIPPET_CACHE[snippet_name]

    snippet_path = os.path.join(SNIPPET_DIR, snippet_name)
    try:
        with open(snippet_path, "r", encoding="utf-8") as f:
            contents = f.read()
            SNIPPET_CACHE[snippet_name] = contents
            return contents
    except OSError:
        return None


def _safe_request_path():
    try:
        return request.path
    except RuntimeError:
        return "<no request>"
