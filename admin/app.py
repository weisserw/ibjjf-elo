import os
import sys
import uuid
import json
import subprocess
import threading
import time
import traceback
import signal
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request, session, jsonify
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
    BackgroundTask,
)
from normalize import normalize

app = Flask(__name__)
app.secret_key = os.environ.get("ADMIN_SECRET_KEY", "default_secret")
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

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


def _append_task_log(task, text):
    task.log_text = (task.log_text or "") + text


def _run_import_task(task_id, args):
    with app.app_context():
        task = BackgroundTask.query.get(task_id)
        if not task:
            return
        task.status = "running"
        task.started_at = datetime.utcnow()
        db.session.commit()

        env = os.environ.copy()
        env["IMPORT_NONINTERACTIVE"] = "1"

        process = subprocess.Popen(
            ["./import.sh"] + args,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        task.pid = process.pid
        db.session.commit()

        buffer = []
        last_flush = time.time()
        try:
            if process.stdout:
                for line in process.stdout:
                    buffer.append(line)
                    if len(buffer) >= 20 or time.time() - last_flush >= 1.0:
                        _append_task_log(task, "".join(buffer))
                        db.session.commit()
                        buffer = []
                        last_flush = time.time()

            return_code = process.wait()
            if buffer:
                _append_task_log(task, "".join(buffer))
            task.exit_code = return_code
            task.finished_at = datetime.utcnow()
            task.status = "success" if return_code == 0 else "error"
            task.pid = None
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            _append_task_log(task, f"\nUnexpected error: {exc}\n")
            _append_task_log(task, traceback.format_exc())
            task.exit_code = -1
            task.finished_at = datetime.utcnow()
            task.status = "error"
            task.pid = None
            db.session.commit()


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


@app.route("/api/bjjcompsystem/tournaments")
def bjjcompsystem_tournaments():
    url = "https://www.bjjcompsystem.com/"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        select = soup.find("select", id="tournament_id")
        if not select:
            return jsonify({"error": "tournament select not found"}), 502
        options = []
        for option in select.find_all("option"):
            value = (option.get("value") or "").strip()
            label = option.get_text(strip=True)
            if value:
                options.append({"id": value, "name": label})
        return jsonify({"tournaments": options})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.route("/tasks")
def tasks_index():
    tasks = (
        BackgroundTask.query.order_by(BackgroundTask.created_at.desc()).limit(10).all()
    )
    return render_template("tasks_index.html", tasks=tasks)


@app.route("/tasks/import", methods=["GET", "POST"])
def tasks_import():
    error = None
    if request.method == "POST":
        tournament_id = request.form.get("tournament_id", "").strip()
        tournament_name = request.form.get("tournament_name", "").strip()
        gi_mode = request.form.get("gi_mode", "gi")
        retries = request.form.get("retries", "2").strip()
        allow_errors = request.form.get("allow_errors") == "on"
        incomplete = request.form.get("incomplete") == "on"

        if not tournament_id or not tournament_name:
            error = "Tournament ID and Tournament Name are required."
        else:
            try:
                retries_int = max(0, int(retries))
            except ValueError:
                error = "Retries must be a number."
                retries_int = 2

        if not error:
            args = [
                tournament_id,
                tournament_name,
                "--gi" if gi_mode == "gi" else "--nogi",
                "--retries",
                str(retries_int),
            ]
            if allow_errors:
                args.append("--allow-errors")
            if incomplete:
                args.append("--incomplete")

            params = {
                "tournament_id": tournament_id,
                "tournament_name": tournament_name,
                "gi_mode": gi_mode,
                "retries": retries_int,
                "allow_errors": allow_errors,
                "incomplete": incomplete,
            }

            task = BackgroundTask(
                task_type="import_results",
                status="queued",
                params_json=json.dumps(params),
            )
            db.session.add(task)
            db.session.commit()

            thread = threading.Thread(
                target=_run_import_task, args=(task.id, args), daemon=True
            )
            thread.start()

            return redirect(url_for("task_detail", task_id=task.id))

    return render_template("tasks_import.html", error=error)


@app.route("/tasks/<task_id>")
def task_detail(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    params = {}
    if task and task.params_json:
        try:
            params = json.loads(task.params_json)
        except json.JSONDecodeError:
            params = {}
    return render_template("task_detail.html", task=task, params=params)


@app.route("/api/tasks/<task_id>")
def task_status(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "status": task.status,
            "exit_code": task.exit_code,
            "log_text": task.log_text or "",
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }
    )


@app.route("/tasks/<task_id>/mark_finished", methods=["POST"])
def task_mark_finished(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if task:
        task.status = "manual"
        task.finished_at = datetime.utcnow()
        task.pid = None
        db.session.commit()
    return redirect(url_for("task_detail", task_id=task_id))


@app.route("/tasks/<task_id>/cancel", methods=["POST"])
def task_cancel(task_id):
    task = BackgroundTask.query.get(uuid.UUID(task_id))
    if not task:
        return redirect(url_for("tasks_index"))

    if task.status in ["running", "queued"]:
        pid = task.pid
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
                time.sleep(1.5)
                os.killpg(pid, 0)
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                _append_task_log(task, f"\nCancel error: {exc}\n")
        task.status = "cancelled"
        task.finished_at = datetime.utcnow()
        task.exit_code = None
        task.pid = None
        db.session.commit()

    return redirect(url_for("task_detail", task_id=task_id))


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
        .order_by(
            LiveStream.day_number,
            LiveStream.mat_number,
            LiveStream.start_hour,
            LiveStream.start_minute,
            LiveStream.start_seconds,
        )
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
        hide_all_str = request.form.get("hide_all")
        try:
            drift_factor = float(drift_factor_str)
            if drift_factor < 0.0001 or drift_factor > 1.2000:
                raise ValueError
        except ValueError:
            drift_factor = 1.0000  # Default drift factor

        hide_all = bool(hide_all_str)

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
                hide_all=hide_all,
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
                stream.hide_all = hide_all
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
            .order_by(
                LiveStream.day_number,
                LiveStream.mat_number,
                LiveStream.start_hour,
                LiveStream.start_minute,
                LiveStream.start_seconds,
            )
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

        bjjheroes_link = request.form.get("bjjheroes_link", "").strip()
        athlete.bjjheroes_link = bjjheroes_link if bjjheroes_link else None

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
            match_video_links[match_id] = value.strip() if value else None
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
