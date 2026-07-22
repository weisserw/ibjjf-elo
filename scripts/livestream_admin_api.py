"""Shared HTTP retry handling for livestream admin API workers."""

from __future__ import annotations

import sys
import time

import requests


ADMIN_API_MAX_ATTEMPTS = 4
ADMIN_API_RETRY_BACKOFF_SECONDS = 1
ADMIN_API_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
ADMIN_API_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _wait_before_retry(method, url, reason, attempt, max_attempts):
    delay = ADMIN_API_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
    print(
        f"admin API {method} {url} {reason}; "
        f"retrying in {delay}s (attempt {attempt + 1}/{max_attempts})",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(delay)


def request_with_retries(
    session, method: str, url: str, *, replay_safe=False, **kwargs
):
    """Send an admin API request, retrying only when replay is explicitly safe."""
    max_attempts = ADMIN_API_MAX_ATTEMPTS if replay_safe else 1
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.request(method, url, **kwargs)
        except ADMIN_API_RETRYABLE_EXCEPTIONS as exc:
            if attempt == max_attempts:
                raise
            _wait_before_retry(
                method,
                url,
                f"failed with {type(exc).__name__}: {exc}",
                attempt,
                max_attempts,
            )
            continue

        if (
            response.status_code in ADMIN_API_RETRYABLE_STATUS_CODES
            and attempt < max_attempts
        ):
            _wait_before_retry(
                method,
                url,
                f"returned HTTP {response.status_code}",
                attempt,
                max_attempts,
            )
            continue
        return response

    raise AssertionError("admin API retry loop exited without a response")
