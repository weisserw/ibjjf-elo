import os
import sys
import uuid
from flask import Flask, render_template, redirect, url_for, request, session

# Ensure app directory is in sys.path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../app")))
from extensions import db
from models import Athlete
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


application = app

if __name__ == "__main__":
    app.run()
