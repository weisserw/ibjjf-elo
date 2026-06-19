import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


YOUTUBE_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")


def parse_time_offset(value: str) -> int:
    value = (value or "").strip().lower()
    if value.isdigit():
        return int(value)

    total = 0
    matched = False
    for amount, unit in re.findall(r"(\d+)\s*([hms])", value):
        matched = True
        number = int(amount)
        if unit == "h":
            total += number * 3600
        elif unit == "m":
            total += number * 60
        elif unit == "s":
            total += number

    if matched:
        return total

    raise ValueError(f"Could not parse YouTube time offset: {value!r}")


def offset_from_url(url: str) -> int:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("t", "start"):
        values = query.get(key)
        if values:
            return parse_time_offset(values[0])

    fragment_query = parse_qs(parsed.fragment)
    values = fragment_query.get("t")
    if values:
        return parse_time_offset(values[0])

    if parsed.fragment.startswith("t="):
        return parse_time_offset(parsed.fragment[2:])

    return 0


def strip_offset_from_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query.pop("t", None)
    query.pop("start", None)
    clean_query = urlencode(query, doseq=True)
    fragment = "" if parsed.fragment.startswith("t=") else parsed.fragment
    return urlunparse(parsed._replace(query=clean_query, fragment=fragment))


def canonical_youtube_url(youtube_video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={youtube_video_id}"


def extract_youtube_video_id(url: str) -> str | None:
    if not url:
        return None

    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    video_id = None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [None])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2 and parts[0] in ("embed", "live", "shorts"):
                video_id = parts[1]
    elif host == "youtu.be":
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            video_id = parts[0]

    if video_id:
        video_id = video_id.strip()
        if YOUTUBE_VIDEO_ID_RE.match(video_id):
            return video_id

    return None
