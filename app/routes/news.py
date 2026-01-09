from flask import Blueprint, jsonify, request
from datetime import date
from extensions import db
from sqlalchemy import text
import requests

WP_API = (
    "https://public-api.wordpress.com/rest/v1.1/sites/ibjjfrankings.wordpress.com/posts"
)

news_route = Blueprint("news_route", __name__)


@news_route.route("/api/news")
def get_news():
    resp = requests.get(
        WP_API, params={"per_page": 5, "order": "desc", "orderby": "date"}
    )

    if resp.status_code != 200:
        return jsonify({"error": resp.text})

    return jsonify({"posts": resp.json()["posts"]})


@news_route.route("/api/news/<id>")
def get_news_by_id(id):
    resp = requests.get(f"{WP_API}/{id}")
    if resp.status_code != 200:
        return jsonify({"error": resp.text})
    return jsonify({"post": resp.json()})


@news_route.route("/api/news/<int:post_id>/view", methods=["POST"])
def log_news_view(post_id):
    ua = request.headers.get("User-Agent", "")
    if "bot" in ua.lower():
        return jsonify({"ok": True, "ignored": "bot"}), 200

    today = date.today()

    db.session.execute(
        text(
            """
      INSERT INTO news_views_daily (post_id, day, views)
      VALUES (:post_id, :day, 1)
      ON CONFLICT (post_id, day)
      DO UPDATE SET views = news_views_daily.views + 1
    """
        ),
        {"post_id": post_id, "day": today},
    )

    db.session.commit()

    return jsonify({"ok": True}), 200
