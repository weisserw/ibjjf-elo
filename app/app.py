import os
import logging
from flask import Flask, request, send_from_directory
from extensions import db, migrate
from seo import (
    render_index_with_fallback,
    render_index_with_snippet,
    render_athlete_page,
)
from routes.top import top_route
from routes.matches import matches_route
from routes.athletes import athletes_route
from routes.events import events_route
from routes.brackets import brackets_route
from routes.news import news_route

logger = logging.getLogger("ibjjf")
log_level = logging.DEBUG if os.getenv("DEBUG") else logging.INFO
logger.setLevel(log_level)
ch = logging.StreamHandler()
ch.setLevel(log_level)
formatter = logging.Formatter(
    "%(asctime)s:%(filename)s:%(lineno)d:%(levelname)s:%(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
ch.setFormatter(formatter)

# Add the handler to the logger
logger.addHandler(ch)
app = Flask(__name__, static_folder="frontend/dist", static_url_path="/")
if os.getenv("DATABASE_URL"):
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"

db.init_app(app)
migrate.init_app(app, db)


@app.route("/")
def index():
    return render_index_with_fallback(app)


@app.route("/athlete/<athlete_id>")
def athlete_page(athlete_id):
    return render_athlete_page(app, athlete_id)


@app.route("/about")
def about():
    return render_index_with_snippet(app, "about.html")


@app.route("/calculator")
def calculator():
    return render_index_with_snippet(app, "calculator.html")


@app.route("/database")
def database():
    return render_index_with_snippet(app, "database.html")


@app.route("/tournaments")
def tournaments():
    return render_index_with_snippet(app, "tournaments.html")


@app.route("/tournaments/registrations")
def tournaments_registrations():
    return render_index_with_snippet(app, "tournaments_registrations.html")


@app.route("/tournaments/archive")
def tournaments_archive():
    return render_index_with_snippet(app, "tournaments_archive.html")


@app.route("/news")
def news():
    return render_index_with_snippet(app, "news.html")


@app.errorhandler(404)
def not_found(e):
    return send_from_directory(app.static_folder, "index.html")


@app.after_request
def add_cache_control_headers(response):
    if request.path.startswith("/api/") or response.mimetype == "text/html":
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.register_blueprint(top_route)
app.register_blueprint(matches_route)
app.register_blueprint(athletes_route)
app.register_blueprint(events_route)
app.register_blueprint(brackets_route)
app.register_blueprint(news_route)

application = app

if __name__ == "__main__":
    app.run()
