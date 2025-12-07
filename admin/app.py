import os
import sys
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request, session
from urllib.parse import urlparse, urlencode, urlunparse


# Ensure app directory is in sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))
from extensions import db
from models import (
    Athlete,
    Event,
    RegistrationLink,
    LiveStream,
    Match,
    MatchParticipant,
    FloEventTag,
)
from normalize import normalize

app = Flask(__name__)
app.secret_key = os.environ.get("ADMIN_SECRET_KEY", "default_secret")

# Use same SQLite DB file as main app by default
default_db_path = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../app/instance/app.db")
)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{default_db_path}")
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

# Admin password
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


# Simple authentication
@app.before_request
def require_login():
    if request.endpoint == "login" or request.endpoint == "static":
        return
    if "logged_in" not in session:
        return redirect(url_for("login"))


@app.after_request
def add_cache_control_headers(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Invalid password")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/events/upcoming")
def upcoming_events():
    events = (
        RegistrationLink.query.filter(RegistrationLink.hidden.isnot(True))
        .filter(RegistrationLink.event_end_date > datetime.now() - timedelta(days=1))
        .order_by(RegistrationLink.event_end_date, RegistrationLink.name)
        .all()
    )
    return render_template("events_upcoming.html", events=events)


@app.route("/events/past")
def past_events():
    search_term = request.args.get("search", "")
    events = []
    if search_term:
        events = (
            Event.query.filter(
                Event.normalized_name.ilike(f"%{normalize(search_term)}%")
            )
            .filter(Event.ibjjf_id.isnot(None))
            .order_by(Event.name)
            .limit(30)
            .all()
        )
    return render_template("events_past.html", events=events)


@app.route("/event/livestreams", methods=["GET", "POST"])
def event_livestreams():
    event_id = request.args.get("id")
    name = request.args.get("name")
    error = None

    streams = (
        LiveStream.query.filter(LiveStream.event_id == event_id)
        .order_by(LiveStream.day_number, LiveStream.mat_number)
        .all()
    )

    flo_event_tags = FloEventTag.query.filter(FloEventTag.event_id == event_id).all()

    flo_tag = ""
    if len(flo_event_tags) > 0:
        flo_tag = flo_event_tags[0].tag

    if request.method == "POST":
        action = request.form.get("action")
        day_number = request.form.get("day_number", type=int)
        mat_number = request.form.get("mat_number", type=int)
        link = request.form.get("link", "").strip()
        stream_id = request.form.get("stream_id")
        start_time_str = request.form.get("start_time", "09:29:00")
        end_time_str = request.form.get("end_time", "23:00:00")
        drift_factor_str = request.form.get("drift_factor", "1.0000")
        try:
            drift_factor = float(drift_factor_str)
            if drift_factor < 0.0001 or drift_factor > 1.2000:
                raise ValueError
        except ValueError:
            drift_factor = 1.0000  # Default drift factor

        try:
            comps = start_time_str.split(":")
            if len(comps) < 2 or len(comps) > 3:
                raise ValueError
            start_hour, start_minute = map(int, comps[:2])
            start_seconds = int(comps[2]) if len(comps) == 3 else 0
            if (
                start_hour < 0
                or start_hour > 23
                or start_minute < 0
                or start_minute > 59
                or start_seconds < 0
                or start_seconds > 59
            ):
                raise ValueError
        except ValueError:
            start_hour, start_minute, start_seconds = 9, 29, 0  # Default time

        try:
            comps = end_time_str.split(":")
            if len(comps) != 2:
                raise ValueError
            end_hour, end_minute = map(int, comps)
            if end_hour < 0 or end_hour > 23 or end_minute < 0 or end_minute > 59:
                raise ValueError
        except ValueError:
            end_hour, end_minute = 23, 0  # Default time

        # try to parse link with urllib so we can normalize it
        try:
            parsed_url = urlparse(link)
            if parsed_url.netloc == "youtu.be":
                video_id = parsed_url.path.lstrip("/")
                query = urlencode({"v": video_id})
                parsed_url = parsed_url._replace(
                    netloc="www.youtube.com", path="/watch", query=query
                )
                link = urlunparse(parsed_url)
        except Exception:
            pass  # if parsing fails, keep the original link

        if action == "add":
            new_stream = LiveStream(
                event_id=event_id,
                platform="youtube",
                mat_number=mat_number,
                day_number=day_number,
                start_hour=start_hour,
                start_minute=start_minute,
                start_seconds=start_seconds,
                end_hour=end_hour,
                end_minute=end_minute,
                drift_factor=drift_factor,
                link=link,
            )
            db.session.add(new_stream)
            db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))

        elif action == "edit":
            stream = LiveStream.query.get(uuid.UUID(stream_id))
            if stream:
                stream.day_number = day_number
                stream.mat_number = mat_number
                stream.start_hour = start_hour
                stream.start_minute = start_minute
                stream.start_seconds = start_seconds
                stream.end_hour = end_hour
                stream.end_minute = end_minute
                stream.drift_factor = drift_factor
                stream.link = link
                db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))
        elif action == "delete":
            stream = LiveStream.query.get(uuid.UUID(stream_id))
            if stream:
                db.session.delete(stream)
                db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))
        elif action == "update_flo_tag":
            flo_tag = request.form.get("flo_tag", "").strip()

            if len(flo_event_tags) > 1:
                for event_tag in flo_event_tags[1:]:
                    db.session.delete(event_tag)
                flo_event_tags = flo_event_tags[:1]

            if flo_tag:
                if len(flo_event_tags) > 0:
                    flo_event_tags[0].tag = flo_tag
                else:
                    new_flo_event_tag = FloEventTag(
                        event_id=event_id,
                        tag=flo_tag,
                    )
                    db.session.add(new_flo_event_tag)
            else:
                # If flo_tag is empty, delete existing tag if it exists
                if len(flo_event_tags) > 0:
                    for event_tag in flo_event_tags:
                        db.session.delete(event_tag)
            db.session.commit()
            return redirect(url_for("event_livestreams", id=event_id, name=name))

        streams = (
            LiveStream.query.filter(LiveStream.event_id == event_id)
            .order_by(LiveStream.day_number, LiveStream.mat_number)
            .all()
        )

    return render_template(
        "event_livestreams.html",
        event_id=event_id,
        event_name=name,
        streams=streams,
        error=error,
        flo_tag=flo_tag,
    )


@app.route("/athletes")
@app.route("/athletes", methods=["GET", "POST"])
def athletes():
    search_term = request.args.get("search", "")
    athletes = []
    if search_term:
        # Case-insensitive search
        athletes = (
            Athlete.query.filter(
                Athlete.normalized_name.ilike(f"%{normalize(search_term)}%")
            )
            .order_by(Athlete.name)
            .limit(30)
            .all()
        )
    return render_template("athletes.html", search_term=search_term, athletes=athletes)


@app.route("/athlete_matches")
def athlete_matches():
    athlete_id = request.args.get("id")
    athlete = None
    matches = []
    if athlete_id:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
        if athlete:
            matches = (
                Match.query.filter(
                    db.session.query(MatchParticipant)
                    .filter(
                        MatchParticipant.match_id == Match.id,
                        MatchParticipant.athlete_id == athlete.id,
                    )
                    .exists()
                )
                .order_by(Match.happened_at.desc())
                .all()
            )
            # Add opponent and athlete_participant fields to each match
            for match in matches:
                athlete_participant = None
                opponent = None
                for p in match.participants:
                    if p.athlete_id == athlete.id:
                        athlete_participant = p
                    else:
                        opponent = p
                match.athlete_participant = athlete_participant
                match.opponent = opponent
    return render_template("athlete_matches.html", athlete=athlete, matches=matches)


@app.route("/athlete_edit")
@app.route("/athlete_edit", methods=["GET", "POST"])
def athlete_edit():
    athlete_id = request.args.get("id")
    athlete = None
    message = None
    if athlete_id:
        athlete = Athlete.query.get(uuid.UUID(athlete_id))
    if request.method == "POST" and athlete:
        instagram_profile = request.form.get("instagram_profile", "")
        # Sanitize input: remove URL and @
        instagram_profile = instagram_profile.strip()
        if instagram_profile.startswith("https://www.instagram.com/"):
            instagram_profile = instagram_profile[len("https://www.instagram.com/") :]
            instagram_profile = instagram_profile.rstrip("/")
        if instagram_profile.startswith("@"):
            instagram_profile = instagram_profile[1:]
        athlete.instagram_profile = instagram_profile

        personal_name = request.form.get("personal_name", "").strip()
        athlete.personal_name = personal_name if personal_name else None
        if personal_name:
            athlete.normalized_personal_name = normalize(personal_name)
        else:
            athlete.normalized_personal_name = None

        country = request.form.get("country", "").strip().lower()
        athlete.country = country[:2]

        country_note = request.form.get("country_note", "").strip()
        athlete.country_note = country_note if country_note else None

        country_note_pt = request.form.get("country_note_pt", "").strip()
        athlete.country_note_pt = country_note_pt if country_note_pt else None

        nickname_translation = request.form.get("nickname_translation", "").strip()
        athlete.nickname_translation = (
            nickname_translation if nickname_translation else None
        )

        db.session.commit()
        message = "Athlete info updated."
    return render_template("athlete_edit.html", athlete=athlete, message=message)


@app.route("/update_all_video_links", methods=["POST"])
def update_all_video_links():
    athlete_id = request.form.get("athlete_id")
    # Collect all video_link fields
    match_video_links = {}
    for key, value in request.form.items():
        if key.startswith("video_link_"):
            match_id = key[len("video_link_") :]
            match_video_links[match_id] = value.strip()
    # Update each match
    for match_id, video_link in match_video_links.items():
        match = Match.query.get(uuid.UUID(match_id))
        if match:
            match.video_link = video_link
    db.session.commit()
    return redirect(url_for("athlete_matches", id=athlete_id))


application = app

if __name__ == "__main__":
    app.run()
