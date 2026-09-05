"""Demand-driven, cross-process leased refreshes. HTTP never runs in a handler."""

import logging
import random
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from flask import current_app
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import WatchlistSchedule, WatchlistRefreshSlot
from watchlist_schedule import BASE, SourceError, homepage_links, scan_tournament

log = logging.getLogger("ibjjf.watchlist_refresh")
_capacity = threading.BoundedSemaphore(2)
DISCOVERY = "__discovery__"
LEASE_SECONDS = 90


def utc(value):
    return (
        value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
    )


def database_now():
    return utc(db.session.query(func.now()).scalar())


def ensure_schedule(event_id):
    if db.session.get(WatchlistSchedule, event_id) is None:
        try:
            with db.session.begin_nested():
                db.session.add(WatchlistSchedule(event_id=event_id, failure_count=0))
                db.session.flush()
        except IntegrityError:
            pass


def claim(event_id):
    """Slot first, then tournament; a failed claim releases both by rollback."""
    token = uuid.uuid4()
    now = database_now()
    ensure_schedule(event_id)
    # Also initialize slots for create_all-based test/development databases.
    for slot_id in (1, 2):
        if db.session.get(WatchlistRefreshSlot, slot_id) is None:
            try:
                with db.session.begin_nested():
                    db.session.add(WatchlistRefreshSlot(id=slot_id))
                    db.session.flush()
            except IntegrityError:
                pass
    db.session.commit()
    for slot_id in (1, 2):
        now = database_now()
        count = (
            db.session.query(WatchlistRefreshSlot)
            .filter(
                WatchlistRefreshSlot.id == slot_id,
                or_(
                    WatchlistRefreshSlot.lease_until.is_(None),
                    WatchlistRefreshSlot.lease_until <= now,
                ),
            )
            .update(
                {
                    "owner_token": token,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                },
                synchronize_session=False,
            )
        )
        if not count:
            db.session.rollback()
            continue
        count = (
            db.session.query(WatchlistSchedule)
            .filter(
                WatchlistSchedule.event_id == event_id,
                or_(
                    WatchlistSchedule.lease_until.is_(None),
                    WatchlistSchedule.lease_until <= now,
                ),
                or_(
                    WatchlistSchedule.next_attempt_at.is_(None),
                    WatchlistSchedule.next_attempt_at <= now,
                ),
                or_(
                    WatchlistSchedule.fetched_at.is_(None),
                    WatchlistSchedule.fetched_at <= now - timedelta(seconds=180),
                ),
            )
            .update(
                {
                    "refresh_token": token,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                },
                synchronize_session=False,
            )
        )
        if count:
            db.session.commit()
            log.info(
                "watchlist claim event=%s token=%s slot=%s", event_id, token, slot_id
            )
            return token, slot_id
        db.session.rollback()
        return None
    return None


def owned(event_id, token, now):
    return db.session.query(WatchlistSchedule).filter(
        WatchlistSchedule.event_id == event_id,
        WatchlistSchedule.refresh_token == token,
        WatchlistSchedule.lease_until > now,
    )


def renew(event_id, token, slot_id, remaining):
    now = database_now()
    until = now + timedelta(seconds=min(LEASE_SECONDS, max(0, remaining)))
    slot = (
        db.session.query(WatchlistRefreshSlot)
        .filter(
            WatchlistRefreshSlot.id == slot_id,
            WatchlistRefreshSlot.owner_token == token,
            WatchlistRefreshSlot.lease_until > now,
        )
        .update({"lease_until": until}, synchronize_session=False)
    )
    event = owned(event_id, token, now).update(
        {"lease_until": until}, synchronize_session=False
    )
    if remaining <= 0 or not slot or not event:
        db.session.rollback()
        raise SourceError("lease_lost")
    db.session.commit()


def finish(event_id, token, slot_id, result=None, error=None):
    now = database_now()
    # Lock/check the slot before the event, just as claim and renew do.
    slot = (
        db.session.query(WatchlistRefreshSlot)
        .filter(
            WatchlistRefreshSlot.id == slot_id,
            WatchlistRefreshSlot.owner_token == token,
            WatchlistRefreshSlot.lease_until > now,
        )
        .update({"owner_token": None, "lease_until": None}, synchronize_session=False)
    )
    if not slot:
        db.session.rollback()
        return False
    query = owned(event_id, token, now)
    row = query.first()
    if row is None:
        db.session.rollback()
        return False
    values = {"refresh_token": None, "lease_until": None}
    stale_age = (now - utc(row.fetched_at)).total_seconds() if row.fetched_at else None
    if error:
        failures = row.failure_count + 1
        delay = max(
            min(300, 30 * 2 ** min(failures - 1, 4) * random.uniform(1, 1.2)),
            getattr(error, "retry_after", 0),
        )
        values.update(
            failure_count=failures,
            last_error_code=getattr(error, "code", "refresh_failed"),
            next_attempt_at=now + timedelta(seconds=delay),
        )
    else:
        matches, coverage, discovery = result
        values.update(
            snapshot=matches,
            coverage=coverage,
            discovery=discovery,
            snapshot_version=uuid.uuid4(),
            fetched_at=now,
            failure_count=0,
            last_error_code=None,
            next_attempt_at=now + timedelta(seconds=180),
        )
    count = query.update(values, synchronize_session=False)
    db.session.commit()
    log.info(
        "watchlist publish event=%s token=%s success=%s coverage=%s stale_age=%s",
        event_id,
        token,
        error is None,
        [day.get("state") for day in result[1]] if result else "retained",
        stale_age,
    )
    return bool(count)


def discovery(fetch, token):
    now = database_now()
    ensure_schedule(DISCOVERY)
    row = db.session.get(WatchlistSchedule, DISCOVERY)
    if row.snapshot is not None and utc(row.fetched_at) > now - timedelta(minutes=5):
        links = row.snapshot
        db.session.commit()
        return links
    count = (
        db.session.query(WatchlistSchedule)
        .filter(
            WatchlistSchedule.event_id == DISCOVERY,
            or_(
                WatchlistSchedule.lease_until.is_(None),
                WatchlistSchedule.lease_until <= now,
            ),
        )
        .update(
            {"refresh_token": token, "lease_until": now + timedelta(seconds=90)},
            synchronize_session=False,
        )
    )
    db.session.commit()
    if not count:
        raise SourceError("discovery_busy")
    try:
        links = homepage_links(fetch(BASE + "/?locale=en"))
        now = database_now()
        if not owned(DISCOVERY, token, now).update(
            {
                "snapshot": links,
                "fetched_at": now,
                "refresh_token": None,
                "lease_until": None,
            },
            synchronize_session=False,
        ):
            raise SourceError("lease_lost")
        db.session.commit()
        return links
    finally:
        db.session.rollback()
        owned(DISCOVERY, token, database_now()).update(
            {"refresh_token": None, "lease_until": None}, synchronize_session=False
        )
        db.session.commit()


def _run(app, event, token, slot_id, registrations=False):
    key = "registration:" + event["event_id"] if registrations else event["event_id"]
    started = time.monotonic()
    pages = byte_count = 0
    with app.app_context():
        try:

            def fetch(url):
                nonlocal pages, byte_count
                remaining = 600 - (time.monotonic() - started)
                if remaining < 26:
                    raise SourceError("refresh_deadline")
                renew(key, token, slot_id, remaining)
                # renew commits: there is no checked-out connection during HTTP.
                request_started = time.monotonic()
                kind = (
                    "registrations"
                    if registrations
                    else (
                        "discovery"
                        if url == BASE + "/?locale=en"
                        else "order_of_fights"
                    )
                )
                status = None
                log.info(
                    "watchlist fetch start event=%s token=%s kind=%s url=%s",
                    key,
                    token,
                    kind,
                    url,
                )
                try:
                    with requests.get(
                        url, timeout=(5, 20), allow_redirects=False, stream=True
                    ) as response:
                        pages += 1
                        status = response.status_code
                        if response.status_code != 200:
                            retry = response.headers.get("Retry-After", "0")
                            try:
                                retry = float(retry)
                            except ValueError:
                                try:
                                    retry = max(
                                        0,
                                        (
                                            parsedate_to_datetime(retry)
                                            - datetime.now(timezone.utc)
                                        ).total_seconds(),
                                    )
                                except (ValueError, TypeError):
                                    retry = 0
                            raise SourceError(
                                "upstream_http_" + str(response.status_code), retry
                            )
                        chunks, size = [], 0
                        renewed = time.monotonic()
                        for chunk in response.iter_content(chunk_size=65536):
                            tick = time.monotonic()
                            if tick - started >= 580:
                                raise SourceError("refresh_deadline")
                            if tick - renewed >= 20:
                                renew(key, token, slot_id, 600 - (tick - started))
                                renewed = tick
                            size += len(chunk)
                            if size > 16 * 1024 * 1024:
                                raise SourceError("source_too_large")
                            chunks.append(chunk)
                        byte_count += size
                        renew(key, token, slot_id, 600 - (time.monotonic() - started))
                        log.info(
                            "watchlist fetch complete event=%s token=%s kind=%s "
                            "url=%s status=%s bytes=%s seconds=%.2f",
                            key,
                            token,
                            kind,
                            url,
                            status,
                            size,
                            time.monotonic() - request_started,
                        )
                        return b"".join(chunks).decode(
                            response.encoding or "utf-8", errors="replace"
                        )
                except Exception as exc:
                    log.warning(
                        "watchlist fetch failed event=%s token=%s kind=%s url=%s "
                        "status=%s code=%s seconds=%.2f",
                        key,
                        token,
                        kind,
                        url,
                        status,
                        getattr(exc, "code", type(exc).__name__),
                        time.monotonic() - request_started,
                    )
                    raise

            if registrations:
                from bs4 import BeautifulSoup
                from routes.brackets import (
                    parse_registrations,
                    parse_division,
                    format_division,
                    save_competitors,
                )

                for link in event["links"]:
                    html = fetch(link["url"])
                    soup = BeautifulSoup(html, "html.parser")
                    if not soup.select_one("#registrations-by-category") and not any(
                        "RegistrationCategories" in s.get_text()
                        for s in soup.find_all("script")
                    ):
                        raise SourceError("unrecognized_registrations")
                    data = parse_registrations(soup)
                    divisions = set()
                    for entry in data:
                        try:
                            divisions.add(
                                format_division(parse_division(entry["FriendlyName"]))
                            )
                        except ValueError:
                            pass
                    renew(key, token, slot_id, 600 - (time.monotonic() - started))
                    save_competitors(uuid.UUID(link["id"]), data, divisions)
                result = ([], [], {})
            else:
                links = discovery(fetch, token)
                url = links.get(event["event_id"])
                if not url:
                    if datetime.now().date() < event["start"].date():
                        result = ([], [{"state": "unpublished"}], {})
                    else:
                        raise SourceError("discovery_unavailable")
                else:
                    # Include a calendar-day margin for viewers behind the server's
                    # date. Reduction uses the browser's local date, without TZ conversion.
                    def page_fetch(page_url):
                        # Every page worker has its own session; none is shared
                        # between the bounded executor's threads.
                        with app.app_context():
                            try:
                                return fetch(page_url)
                            finally:
                                db.session.remove()

                    with ThreadPoolExecutor(
                        max_workers=2, thread_name_prefix="watchlist-page"
                    ) as pool:

                        def fetch_many(urls):
                            # The pure scanner submits at most two URLs at a time.
                            return list(pool.map(page_fetch, urls))

                        result = scan_tournament(
                            fetch,
                            url,
                            event,
                            datetime.now().date() - timedelta(days=1),
                            fetch_many,
                        )
            renew(key, token, slot_id, 600 - (time.monotonic() - started))
            finish(key, token, slot_id, result=result)
        except Exception as exc:
            db.session.rollback()
            log.warning(
                "watchlist failed event=%s token=%s code=%s",
                key,
                token,
                getattr(exc, "code", type(exc).__name__),
            )
            try:
                finish(key, token, slot_id, error=exc)
            except Exception:
                db.session.rollback()
                log.exception("watchlist lease release failed event=%s", key)
        finally:
            log.info(
                "watchlist scan event=%s token=%s pages=%s bytes=%s seconds=%.2f",
                key,
                token,
                pages,
                byte_count,
                time.monotonic() - started,
            )
            db.session.remove()
            _capacity.release()


def trigger(event, registrations=False):
    if current_app.config.get("WATCHLIST_REFRESH_ENABLED", True) is False:
        return False
    if not _capacity.acquire(blocking=False):
        return False
    key = "registration:" + event["event_id"] if registrations else event["event_id"]
    lease = None
    try:
        lease = claim(key)
        if not lease:
            _capacity.release()
            return False
        app = current_app._get_current_object()
        threading.Thread(
            target=_run,
            args=(app, event, *lease, registrations),
            daemon=True,
            name="watchlist-" + key,
        ).start()
        return True
    except Exception as exc:
        db.session.rollback()
        try:
            if lease:
                finish(key, *lease, error=exc)
        finally:
            _capacity.release()
        log.exception("watchlist startup failed event=%s", key)
        return False
