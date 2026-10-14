"""Seekable, bounded HTTP downloads for ffmpeg on older FFmpeg releases."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import re
import threading
from urllib.parse import urlparse
import uuid

import requests


@contextmanager
def chunked_media_source(url, selected, log=print):
    """Honor yt-dlp's chunk size without downloading an entire video to disk.

    ffmpeg seeks against a loopback endpoint. Each requested byte range is
    streamed from bounded upstream requests, retaining the extractor headers.
    HLS manifests and already-downloaded DASH sections pass through unchanged.
    """
    chunk_size = (selected.get("downloader_options") or {}).get("http_chunk_size")
    if (
        selected.get("protocol") not in ("http", "https")
        or urlparse(url).scheme not in ("http", "https")
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
    ):
        yield url
        return

    headers = {
        key: value
        for key, value in (selected.get("http_headers") or {}).items()
        if key.lower() not in ("range", "accept-encoding", "host", "connection")
    }
    headers["Accept-Encoding"] = "identity"
    route = f"/{uuid.uuid4().hex}"
    stopped = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.path != route:
                self.send_error(404)
                return
            requested_range = self.headers.get("Range")
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested_range or "bytes=0-")
            if not match:
                self.send_error(416)
                return
            offset = int(match[1])
            requested_end = int(match[2]) if match[2] else None
            if requested_end is not None and requested_end < offset:
                self.send_error(416)
                return
            sent_headers = False
            total_size = None
            target_end = requested_end
            try:
                with requests.Session() as session:
                    while not stopped.is_set():
                        end = offset + chunk_size - 1
                        if target_end is not None:
                            end = min(end, target_end)
                        request_headers = {**headers, "Range": f"bytes={offset}-{end}"}
                        with session.get(
                            url, headers=request_headers, stream=True, timeout=(10, 30)
                        ) as response:
                            if response.status_code != 206:
                                # Do not expose signed URLs or authentication headers.
                                raise RuntimeError(
                                    f"upstream returned HTTP {response.status_code}; "
                                    "expected a byte-range response"
                                )
                            content_range = re.fullmatch(
                                r"bytes (\d+)-(\d+)/(\d+)",
                                response.headers.get("Content-Range", ""),
                            )
                            if not content_range:
                                raise RuntimeError(
                                    "upstream omitted a valid Content-Range"
                                )
                            first, last, size = map(int, content_range.groups())
                            if (
                                first != offset
                                or last != min(end, size - 1)
                                or size <= last
                                or last < first
                                or (total_size is not None and size != total_size)
                            ):
                                raise RuntimeError(
                                    "upstream returned an inconsistent byte range"
                                )
                            total_size = size
                            target_end = (
                                min(requested_end, size - 1)
                                if requested_end is not None
                                else size - 1
                            )
                            if not sent_headers:
                                self.send_response(206 if requested_range else 200)
                                self.send_header("Accept-Ranges", "bytes")
                                self.send_header(
                                    "Content-Length", str(target_end - offset + 1)
                                )
                                self.send_header(
                                    "Content-Type",
                                    response.headers.get(
                                        "Content-Type", "application/octet-stream"
                                    ),
                                )
                                if requested_range:
                                    self.send_header(
                                        "Content-Range",
                                        f"bytes {offset}-{target_end}/{size}",
                                    )
                                self.end_headers()
                                sent_headers = True
                            remaining = last - first + 1
                            for data in response.iter_content(chunk_size=64 * 1024):
                                if stopped.is_set():
                                    return
                                if len(data) > remaining:
                                    raise RuntimeError(
                                        "upstream exceeded its declared byte range"
                                    )
                                self.wfile.write(data)
                                remaining -= len(data)
                            if remaining:
                                raise RuntimeError(
                                    "upstream ended before its declared byte range"
                                )
                            offset = last + 1
                            if offset > target_end:
                                return
            except (BrokenPipeError, ConnectionResetError):
                # Seeking and finishing a segment close previous ffmpeg reads.
                return
            except (requests.RequestException, RuntimeError) as exc:
                reason = (
                    str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                )
                log(f"Chunked media download failed at byte {offset}: {reason}")
                if not sent_headers:
                    self.send_error(502, "Upstream media download failed")
                self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    thread.start()
    log(f"Using bounded HTTP media requests: chunk_bytes={chunk_size}")
    try:
        yield f"http://127.0.0.1:{server.server_port}{route}"
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join()
