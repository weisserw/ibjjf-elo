"""Turnstile-backed anonymous access to match data.

Only server configuration enables enforcement. Counters live in the database,
so neither changing IP nor switching Gunicorn workers resets a session quota.
"""

import os
import secrets
from time import time

import requests
from flask import Blueprint, current_app, jsonify, request
from itsdangerous import BadData, URLSafeTimedSerializer
from sqlalchemy import case, update

from extensions import db


COOKIE_NAME = "match_access"
ACTION = "match_access"
SITE_KEY = "0x4AAAAAAGDvwrAtybkRVXKi"
SESSION_SECONDS = 3600
BURST_SECONDS = 10
BURST_REQUESTS = 15
SESSION_UNITS = 200
access_route = Blueprint("match_access", __name__)


class MatchAccessSession(db.Model):
    __tablename__ = "match_access_sessions"

    id = db.Column(db.String(64), primary_key=True)
    expires_at = db.Column(db.BigInteger, nullable=False, index=True)
    units = db.Column(db.Integer, nullable=False, default=0)
    burst_bucket = db.Column(db.BigInteger, nullable=False, default=0)
    burst_requests = db.Column(db.Integer, nullable=False, default=0)


def configure_match_access(app):
    app.config.update(
        MATCH_ACCESS_ENABLED=os.getenv("MATCH_ACCESS_ENABLED", "").lower()
        in {"1", "true", "yes"},
        TURNSTILE_SITE_KEY=os.getenv("TURNSTILE_SITE_KEY", SITE_KEY),
        TURNSTILE_SECRET_KEY=os.getenv("TURNSTILE_SECRET_KEY", ""),
        MATCH_ACCESS_SIGNING_KEY=os.getenv("MATCH_ACCESS_SIGNING_KEY", ""),
        TURNSTILE_HOSTNAMES={
            host.strip().lower()
            for host in os.getenv(
                "TURNSTILE_HOSTNAMES", "jiujitsu.net,www.jiujitsu.net"
            ).split(",")
            if host.strip()
        },
    )
    if app.config["MATCH_ACCESS_ENABLED"]:
        if not app.config["TURNSTILE_SECRET_KEY"]:
            raise RuntimeError("MATCH_ACCESS_ENABLED requires TURNSTILE_SECRET_KEY")
        if len(app.config["MATCH_ACCESS_SIGNING_KEY"]) < 32:
            raise RuntimeError(
                "MATCH_ACCESS_SIGNING_KEY must have at least 32 characters"
            )
        if (
            not app.config["TURNSTILE_SITE_KEY"]
            or not app.config["TURNSTILE_HOSTNAMES"]
        ):
            raise RuntimeError("Turnstile site key and hostnames must be configured")


def _signer():
    return URLSafeTimedSerializer(
        current_app.config["MATCH_ACCESS_SIGNING_KEY"], salt="match-access-v1"
    )


def _session_id():
    cookie = request.cookies.get(COOKIE_NAME, "")
    if not cookie or len(cookie) > 512:
        return None
    try:
        identity = _signer().loads(cookie, max_age=SESSION_SECONDS)
        return identity if isinstance(identity, str) else None
    except BadData:
        return None


def require_match_access():
    if (
        not current_app.config.get("MATCH_ACCESS_ENABLED")
        or request.method == "OPTIONS"
    ):
        return None

    identity = _session_id()
    now = int(time())
    if not identity:
        return jsonify(error="Verification required", code="match_access_required"), 403

    # Reserve the maximum number of rows this request can expose, before SQL work.
    units = 1
    if request.path == "/api/matches":
        units = 100 if request.args.get("athlete_id") else 12
    bucket = now // BURST_SECONDS
    session = MatchAccessSession
    result = db.session.execute(
        update(session)
        .where(
            session.id == identity,
            session.expires_at > now,
            session.units + units <= SESSION_UNITS,
            (session.burst_bucket != bucket)
            | (session.burst_requests < BURST_REQUESTS),
        )
        .values(
            units=session.units + units,
            burst_bucket=bucket,
            burst_requests=case(
                (session.burst_bucket == bucket, session.burst_requests + 1),
                else_=1,
            ),
        )
        .execution_options(synchronize_session=False)
    )
    db.session.commit()
    if result.rowcount == 1:
        return None

    existing = db.session.get(session, identity)
    if existing is None or existing.expires_at <= now:
        return jsonify(error="Verification required", code="match_access_required"), 403
    if existing.units + units > SESSION_UNITS:
        # The browser handles this exactly like expiry: obtain fresh Turnstile
        # proof, rotate the session, then retry the original request once.
        return (
            jsonify(
                error="Verification required",
                code="match_access_required",
                reason="quota_exhausted",
            ),
            403,
        )
    retry_after = BURST_SECONDS - now % BURST_SECONDS
    response = jsonify(
        error="Match browsing limit reached. Please try again later.",
        code="match_access_limited",
    )
    response.status_code = 429
    response.headers["Retry-After"] = str(max(1, retry_after))
    return response


@access_route.get("/api/access/config")
def access_config():
    enabled = current_app.config.get("MATCH_ACCESS_ENABLED", False)
    return jsonify(
        enabled=enabled,
        siteKey=current_app.config["TURNSTILE_SITE_KEY"] if enabled else None,
    )


@access_route.post("/api/access/verify")
def verify_access():
    if not current_app.config.get("MATCH_ACCESS_ENABLED"):
        return jsonify(ok=True)
    # Every grant, including renewal of a valid cookie, requires fresh proof.
    # Never reset counters on the same session ID: a copied cookie must stay invalid
    # after the real browser obtains a replacement.
    identity = _session_id()
    if request.content_length is None or request.content_length > 4096:
        return jsonify(error="Invalid verification request"), 400
    payload = request.get_json(silent=True)
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip() or len(token) > 2048:
        return jsonify(error="Invalid verification token"), 400

    try:
        response = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={
                "secret": current_app.config["TURNSTILE_SECRET_KEY"],
                "response": token,
            },
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except (requests.RequestException, ValueError):
        return jsonify(error="Verification unavailable. Please try again."), 503

    if (
        not isinstance(result, dict)
        or result.get("success") is not True
        or result.get("hostname") not in current_app.config["TURNSTILE_HOSTNAMES"]
        or result.get("action") != ACTION
    ):
        return jsonify(error="Verification failed. Please try again."), 403

    now = int(time())
    previous_identity = identity
    identity = secrets.token_hex(32)
    rotated = 0
    if previous_identity:
        # Rotate atomically while retaining the latest burst counters, including
        # requests that arrived while Cloudflare verification was in flight.
        rotated = db.session.execute(
            update(MatchAccessSession)
            .where(MatchAccessSession.id == previous_identity)
            .values(id=identity, expires_at=now + SESSION_SECONDS, units=0)
            .execution_options(synchronize_session=False)
        ).rowcount
    if rotated != 1:
        db.session.add(
            MatchAccessSession(id=identity, expires_at=now + SESSION_SECONDS)
        )
    db.session.commit()
    response = jsonify(ok=True)
    response.set_cookie(
        COOKIE_NAME,
        _signer().dumps(identity),
        max_age=SESSION_SECONDS,
        secure=True,
        httponly=True,
        samesite="Lax",
        path="/api/",
    )
    return response
