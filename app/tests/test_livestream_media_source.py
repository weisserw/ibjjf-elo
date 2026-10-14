from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from livestream_media_source import chunked_media_source


@contextmanager
def media_origin(payload, status=206, wrong_offset=False, fail_after=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append(dict(self.headers))
            match = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
            if not match:
                self.send_error(400)
                return
            start, end = map(int, match.groups())
            end = min(end, len(payload) - 1)
            if fail_after is not None and len(calls) > fail_after:
                self.send_error(403)
                return
            self.send_response(status)
            self.send_header(
                "Content-Range",
                f"bytes {start + int(wrong_offset)}-{end}/{len(payload)}",
            )
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            try:
                self.wfile.write(payload[start : end + 1])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/video", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def selected_format(chunk_size=10):
    return {
        "protocol": "https",
        "downloader_options": {"http_chunk_size": chunk_size},
        "http_headers": {
            "User-Agent": "extractor-agent",
            "Referer": "https://www.youtube.com/",
        },
    }


class ChunkedMediaSourceTests(unittest.TestCase):
    def test_seek_streams_only_requested_range_in_bounded_requests(self):
        payload = bytes(range(100))
        with media_origin(payload) as (origin, calls):
            with chunked_media_source(
                origin, selected_format(), log=lambda _: None
            ) as local:
                response = requests.get(
                    local, headers={"Range": "bytes=53-79"}, timeout=5
                )
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.headers["Content-Range"], "bytes 53-79/100")
                self.assertEqual(response.content, payload[53:80])
        self.assertEqual(
            [c["Range"] for c in calls], ["bytes=53-62", "bytes=63-72", "bytes=73-79"]
        )
        self.assertTrue(all(c["User-Agent"] == "extractor-agent" for c in calls))
        self.assertTrue(all(c["Referer"] == "https://www.youtube.com/" for c in calls))

    def test_open_range_and_full_download_reassemble_exact_bytes(self):
        payload = bytes(range(43))
        with media_origin(payload) as (origin, _):
            with chunked_media_source(
                origin, selected_format(), log=lambda _: None
            ) as local:
                for headers, expected_status, expected in [
                    ({}, 200, payload),
                    ({"Range": "bytes=22-"}, 206, payload[22:]),
                    ({"Range": "bytes=32-1000"}, 206, payload[32:]),
                ]:
                    with self.subTest(headers=headers):
                        response = requests.get(local, headers=headers, timeout=5)
                        self.assertEqual(response.status_code, expected_status)
                        self.assertEqual(response.content, expected)

    def test_upstream_errors_and_invalid_ranges_fail_without_leaking_url(self):
        for status, wrong_offset in [(403, False), (200, False), (206, True)]:
            with self.subTest(status=status, wrong_offset=wrong_offset):
                messages = []
                with media_origin(bytes(range(30)), status, wrong_offset) as (
                    origin,
                    _,
                ):
                    with chunked_media_source(
                        origin + "?secret=value", selected_format(), log=messages.append
                    ) as local:
                        response = requests.get(local, timeout=5)
                        self.assertEqual(response.status_code, 502)
                self.assertNotIn("secret", " ".join(messages) + response.text)

    def test_invalid_local_range_does_not_contact_upstream(self):
        with media_origin(bytes(range(30))) as (origin, calls):
            with chunked_media_source(
                origin, selected_format(), log=lambda _: None
            ) as local:
                for value in ["bytes=20-10", "bytes=-10", "bytes=1-2,4-5"]:
                    response = requests.get(local, headers={"Range": value}, timeout=5)
                    self.assertEqual(response.status_code, 416)
        self.assertEqual(calls, [])

    def test_failure_mid_download_is_not_reported_as_complete(self):
        with media_origin(bytes(range(30)), fail_after=1) as (origin, _):
            with chunked_media_source(
                origin, selected_format(), log=lambda _: None
            ) as local:
                with self.assertRaises(requests.exceptions.ChunkedEncodingError):
                    requests.get(local, timeout=5)

    def test_hls_local_dash_and_unmarked_sources_pass_through(self):
        for url, selected in [
            (
                "https://example.com/video.m3u8",
                {**selected_format(), "protocol": "m3u8_native"},
            ),
            ("/tmp/dash-section.mp4", selected_format()),
            ("https://example.com/video", {"protocol": "https"}),
        ]:
            with chunked_media_source(url, selected) as source:
                self.assertEqual(source, url)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_ffmpeg_seeks_and_decodes_same_frames_as_local_file(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=size=64x64:rate=10:duration=4",
                    "-c:v",
                    "mpeg4",
                    "-movflags",
                    "+faststart",
                    str(video),
                ],
                check=True,
                capture_output=True,
                timeout=15,
            )

            def frames(source):
                return subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        "2",
                        "-t",
                        "1",
                        "-i",
                        source,
                        "-vf",
                        "fps=2",
                        "-f",
                        "framemd5",
                        "-",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=15,
                ).stdout

            expected = frames(str(video))
            with media_origin(video.read_bytes()) as (origin, calls):
                with chunked_media_source(
                    origin, selected_format(1024), log=lambda _: None
                ) as local:
                    self.assertEqual(frames(local), expected)
            self.assertGreater(len(calls), 1)
            for call in calls:
                start, end = map(
                    int, re.fullmatch(r"bytes=(\d+)-(\d+)", call["Range"]).groups()
                )
                self.assertLessEqual(end - start + 1, 1024)
