from flask import Blueprint, jsonify
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
