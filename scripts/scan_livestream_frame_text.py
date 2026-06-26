#!/usr/bin/env python3
"""Scan archived livestream frame crops for sparse scoreboard/timer text events."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "app"
sys.path.insert(0, str(APP_DIR))

from extensions import db  # noqa: E402
from livestream_frame_text_scan import (  # noqa: E402
    DEFAULT_COARSE_INTERVAL_SECONDS,
    DEFAULT_NAME_ENGINE,
    DEFAULT_PARSER_PROFILE,
    DEFAULT_SCORE_ENGINE,
    FrameReading,
    S3FrameBatchProvider,
    TextState,
    mark_text_scan_segment_error,
    mark_text_scan_segment_success,
    reconstruct_text_state,
    scan_frame_text_segment,
    claim_next_text_scan_segment,
)
from models import LivestreamFrameCaptureSegment  # noqa: E402
from photos import bucket_name, get_s3_client  # noqa: E402


ADMIN_URL_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_URL"
ADMIN_PASSWORD_ENV_VAR = "LIVESTREAM_ARCHIVE_ADMIN_PASSWORD"
SUPPORTED_ENGINES = ("none", "tesseract", "paddle")


class ApiObject:
    def __init__(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                value = ApiObject(value)
            elif isinstance(value, list):
                value = [
                    ApiObject(item) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)

    def update_from(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                current = getattr(self, key, None)
                if isinstance(current, ApiObject):
                    current.update_from(value)
                    value = current
                else:
                    value = ApiObject(value)
            elif isinstance(value, list):
                value = [
                    ApiObject(item) if isinstance(item, dict) else item
                    for item in value
                ]
            setattr(self, key, value)


class LocalTextScanState:
    def claim_next_segment(
        self,
        scan_id=None,
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        return claim_next_text_scan_segment(
            db.session,
            scan_id=scan_id,
            archive_id=archive_id,
            youtube_video_id=youtube_video_id,
            background_task_id=background_task_id,
        )

    def capture_segments_for_archive(self, archive_id):
        return (
            LivestreamFrameCaptureSegment.query.filter_by(
                archive_id=archive_id, status="success"
            )
            .order_by(LivestreamFrameCaptureSegment.start_second)
            .all()
        )

    def initial_state_for_segment(self, segment):
        return reconstruct_text_state(
            db.session, segment.archive_id, before_second=segment.start_second
        )

    def mark_success(self, segment, events):
        mark_text_scan_segment_success(db.session, segment, events)
        db.session.commit()

    def mark_error(self, segment, error: str):
        mark_text_scan_segment_error(db.session, segment, error)
        db.session.commit()


class AdminApiTextScanState:
    def __init__(self, base_url: str, password: str, session=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.password = password
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        headers["X-Admin-Password"] = self.password
        response = self.session.request(
            method,
            urljoin(self.base_url, path.lstrip("/")),
            headers=headers,
            timeout=60,
            **kwargs,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code >= 400:
            message = payload.get("error") or response.text
            raise RuntimeError(
                f"admin API {method} {path} failed "
                f"with HTTP {response.status_code}: {message}"
            )
        return payload

    def claim_next_segment(
        self,
        scan_id=None,
        archive_id=None,
        youtube_video_id=None,
        background_task_id=None,
    ):
        payload = self._request(
            "POST",
            "/api/livestream_frame_archives/worker/text_scan_segments/claim",
            json={
                "scan_id": str(scan_id) if scan_id else None,
                "archive_id": str(archive_id) if archive_id else None,
                "youtube_video_id": youtube_video_id,
                "background_task_id": (
                    str(background_task_id) if background_task_id else None
                ),
            },
        )
        segment = payload.get("segment")
        return ApiObject(segment) if segment else None

    def capture_segments_for_archive(self, archive_id):
        raise RuntimeError("admin API segments include archive_capture_segments")

    def initial_state_for_segment(self, segment):
        payload = self._request(
            "GET",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/initial_state",
        )
        return TextState(**payload["state"])

    def mark_success(self, segment, events):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/complete",
            json={"events": [event_payload(event) for event in events]},
        )
        segment.update_from(payload["segment"])

    def mark_error(self, segment, error: str):
        payload = self._request(
            "POST",
            f"/api/livestream_frame_archives/worker/text_scan_segments/{segment.id}/error",
            json={"error": error},
        )
        segment.update_from(payload["segment"])


class EmptyTextParser:
    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        return FrameReading(frame_second=frame_second, score_engine="none")


class TesseractTextParser:
    SCORE_DIGIT_TEMPLATE_SIZE = (24, 36)
    SCORE_DIGIT_MIN_MATCH = 0.78

    def __init__(self, parser_profile: str, score_engine: str, name_engine: str | None):
        self.parser_profile = parser_profile
        self.score_engine = score_engine
        self.name_engine = name_engine
        self._score_digit_templates_cache = None
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401

    def _image_from_bytes(self, image_bytes):
        if not image_bytes:
            return None
        from PIL import Image
        import io

        return Image.open(io.BytesIO(image_bytes))

    def _ocr(self, image, config: str = "") -> str:
        if image is None:
            return ""
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip()

    def _ocr_digit_text(self, image, config: str = "--psm 6") -> str:
        return self._ocr(
            image,
            f"{config} -c tessedit_char_whitelist=0123456789OoIl",
        )

    def _parse_timer(self, text: str) -> tuple[str | None, str | None]:
        match = re.search(r"\b(\d{1,2})\s*[:;]\s*(\d{2})\b", text)
        if not match:
            return None, None
        return "running", f"{int(match.group(1))}:{match.group(2)}"

    def _score_token_value(self, token: str) -> int | None:
        token = token.strip()
        if not token:
            return None
        token = token.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1"}))
        if not re.fullmatch(r"\d{1,2}", token):
            return None
        return int(token)

    def _score_row_values(self, line: str) -> list[int] | None:
        tokens = []
        for match in re.findall(r"[0-9OoIl]+", line):
            if len(match) >= 3:
                tokens.extend(match)
            else:
                tokens.append(match)
        values = []
        for token in tokens:
            value = self._score_token_value(token)
            if value is not None:
                values.append(value)
        if len(values) < 3:
            return None
        return values[-3:]

    def _score_grid_image(self, score_image):
        if score_image is None:
            return None
        width, height = score_image.size
        return score_image.crop(
            (
                int(width * 0.47),
                0,
                int(width * 0.92),
                int(height * 0.88),
            )
        )

    def _prepare_score_image(self, image):
        from PIL import ImageOps

        gray = ImageOps.grayscale(image)
        return gray.resize((gray.width * 5, gray.height * 5))

    def _prepare_score_cell_image(self, image):
        from PIL import ImageEnhance, ImageOps

        gray = ImageOps.grayscale(image).resize((image.width * 8, image.height * 8))
        boosted = ImageEnhance.Contrast(gray).enhance(3)
        return boosted.point(lambda value: 255 if value > 180 else 0)

    def _score_cell_inner_image(self, image):
        margin = max(2, min(image.size) // 12)
        return image.crop(
            (
                margin,
                margin,
                image.width - margin,
                image.height - margin,
            )
        )

    def _score_cell_has_background(self, image, cell_index: int) -> bool:
        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        if width == 0 or height == 0:
            return False

        pixels = rgb_image.load()
        background_pixels = 0
        for y in range(height):
            for x in range(width):
                red, green, blue = pixels[x, y]
                if cell_index % 3 == 2:
                    if red > 120 and green < 90 and blue < 110:
                        background_pixels += 1
                elif green > 110 and blue < 100:
                    background_pixels += 1

        return background_pixels >= width * height * 0.12

    def _score_digit_font_candidates(self):
        return (
            "Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "Verdana Bold.ttf",
            "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
            "DejaVuSans-Bold.ttf",
        )

    def _score_digit_templates(self):
        if self._score_digit_templates_cache is not None:
            return self._score_digit_templates_cache

        from PIL import Image, ImageDraw, ImageFont

        templates = []
        loaded_font = None
        for font_path in self._score_digit_font_candidates():
            try:
                ImageFont.truetype(font_path, 32)
                loaded_font = font_path
                break
            except OSError:
                continue

        width, height = self.SCORE_DIGIT_TEMPLATE_SIZE
        for digit in range(10):
            for font_size in range(28, 45, 4):
                font = (
                    ImageFont.load_default()
                    if loaded_font is None
                    else ImageFont.truetype(loaded_font, font_size)
                )
                canvas = Image.new("L", (80, 80), 0)
                draw = ImageDraw.Draw(canvas)
                bbox = draw.textbbox((0, 0), str(digit), font=font)
                draw.text(
                    (5 - bbox[0], 5 - bbox[1]),
                    str(digit),
                    font=font,
                    fill=255,
                )
                glyph_box = canvas.getbbox()
                if glyph_box is None:
                    continue
                glyph = canvas.crop(glyph_box).resize(
                    (width, height), Image.Resampling.NEAREST
                )
                mask = 0
                pixel_count = 0
                for y in range(height):
                    for x in range(width):
                        if glyph.getpixel((x, y)) > 0:
                            mask |= 1 << (y * width + x)
                            pixel_count += 1
                templates.append((digit, mask, pixel_count))

        self._score_digit_templates_cache = templates
        return templates

    def _score_digit_mask(self, image):
        from PIL import Image

        rgb_image = image.convert("RGB")
        width, height = rgb_image.size
        pixels = rgb_image.load()
        foreground = bytearray(width * height)
        for y in range(height):
            for x in range(width):
                red, green, blue = pixels[x, y]
                if (
                    red > 145
                    and green > 145
                    and blue > 95
                    and max(red, green, blue) - min(red, green, blue) < 120
                ):
                    foreground[y * width + x] = 1

        seen = bytearray(width * height)
        largest_component = []
        for index, is_foreground in enumerate(foreground):
            if not is_foreground or seen[index]:
                continue

            stack = [index]
            seen[index] = 1
            component = []
            while stack:
                current = stack.pop()
                component.append(current)
                x = current % width
                y = current // width
                neighbors = []
                if x > 0:
                    neighbors.append(current - 1)
                if x + 1 < width:
                    neighbors.append(current + 1)
                if y > 0:
                    neighbors.append(current - width)
                if y + 1 < height:
                    neighbors.append(current + width)
                for neighbor in neighbors:
                    if foreground[neighbor] and not seen[neighbor]:
                        seen[neighbor] = 1
                        stack.append(neighbor)

            if len(component) > len(largest_component):
                largest_component = component

        if len(largest_component) < 40:
            return None

        xs = [index % width for index in largest_component]
        ys = [index // width for index in largest_component]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        glyph_width = right - left + 1
        glyph_height = bottom - top + 1
        glyph_data = bytearray(glyph_width * glyph_height)
        for index in largest_component:
            point_x = index % width
            point_y = index // width
            glyph_data[(point_y - top) * glyph_width + point_x - left] = 255
        glyph = Image.frombytes("L", (glyph_width, glyph_height), bytes(glyph_data))

        template_width, template_height = self.SCORE_DIGIT_TEMPLATE_SIZE
        glyph = glyph.resize(
            (template_width, template_height), Image.Resampling.NEAREST
        )
        mask = 0
        pixel_count = 0
        for y in range(template_height):
            for x in range(template_width):
                if glyph.getpixel((x, y)) > 0:
                    mask |= 1 << (y * template_width + x)
                    pixel_count += 1
        return mask, pixel_count

    def _template_score_digit(self, image, cell_index: int) -> tuple[int | None, str]:
        inner_image = self._score_cell_inner_image(image)
        if not self._score_cell_has_background(inner_image, cell_index):
            return None, ""

        digit_mask_data = self._score_digit_mask(inner_image)
        if not digit_mask_data:
            return None, ""
        digit_mask, digit_pixel_count = digit_mask_data

        best_digit = None
        best_score = 0.0
        for digit, template_mask, template_pixel_count in self._score_digit_templates():
            intersection = (digit_mask & template_mask).bit_count()
            union = digit_pixel_count + template_pixel_count - intersection
            score = intersection / union if union else 0.0
            if score > best_score:
                best_digit = digit
                best_score = score

        if best_digit is None or best_score < self.SCORE_DIGIT_MIN_MATCH:
            return None, ""
        return best_digit, str(best_digit)

    def _score_cell_boxes(self, score_image):
        width, height = score_image.size
        x_edges = (0.481, 0.638, 0.791, 0.919)
        y_edges = (0.0, 0.431, 0.861)
        return [
            (
                int(width * x_edges[col]),
                int(height * y_edges[row]),
                int(width * x_edges[col + 1]),
                int(height * y_edges[row + 1]),
            )
            for row in range(2)
            for col in range(3)
        ]

    def _score_image_has_cell_layout(self, score_image) -> bool:
        if score_image is None:
            return False
        for cell_index, box in enumerate(self._score_cell_boxes(score_image)):
            cell_image = self._score_cell_inner_image(score_image.crop(box))
            if not self._score_cell_has_background(cell_image, cell_index):
                return False
        return True

    def _ocr_score_cell(self, image) -> tuple[int | None, str]:
        prepared = self._prepare_score_cell_image(image)
        for psm in ("--psm 8", "--psm 13"):
            text = self._ocr_digit_text(prepared, psm).replace("\n", "").strip()
            value = self._score_token_value(text)
            if value is not None and 0 <= value <= 9:
                return value, text
        return None, ""

    def _parse_score_cells_from_image(self, score_image) -> tuple[dict, str]:
        if score_image is None:
            return {}, ""

        values = []
        cell_texts = []
        for cell_index, box in enumerate(self._score_cell_boxes(score_image)):
            cell_image = score_image.crop(box)
            value, text = self._template_score_digit(cell_image, cell_index)
            values.append(value)
            cell_texts.append(str(value) if value is not None else (text or "?"))
        cell_text = "".join(cell_texts[:3])
        cell_text += "\n" + "".join(cell_texts[3:])
        if any(value is None for value in values):
            return {}, cell_text
        return (
            {
                "top_points": values[0],
                "top_advantages": values[1],
                "top_penalties": values[2],
                "bottom_points": values[3],
                "bottom_advantages": values[4],
                "bottom_penalties": values[5],
            },
            cell_text,
        )

    def _ocr_score_row(self, image) -> tuple[list[int] | None, str]:
        for psm in ("--psm 7", "--psm 8", "--psm 13"):
            text = self._ocr_digit_text(image, psm)
            row = self._score_row_values(text)
            if row:
                return row, text
        return None, ""

    def _parse_score_from_image(self, score_image) -> tuple[dict, str]:
        if not self._score_image_has_cell_layout(score_image):
            return {}, ""

        cell_fields, cell_text = self._parse_score_cells_from_image(score_image)
        if cell_fields:
            return cell_fields, cell_text

        grid_image = self._score_grid_image(score_image)
        if grid_image is None:
            return {}, cell_text

        prepared_grid = self._prepare_score_image(grid_image)
        grid_text = self._ocr_digit_text(prepared_grid, "--psm 6")
        score_fields = self._parse_score(grid_text)
        if score_fields:
            return score_fields, grid_text

        width, height = prepared_grid.size
        top_row = prepared_grid.crop((0, 0, width, height // 2))
        bottom_row = prepared_grid.crop((0, height // 2, width, height))
        top_values, top_text = self._ocr_score_row(top_row)
        bottom_values, bottom_text = self._ocr_score_row(bottom_row)
        row_text = "\n".join([top_text, bottom_text])
        if top_values and bottom_values:
            return (
                {
                    "top_points": top_values[0],
                    "top_advantages": top_values[1],
                    "top_penalties": top_values[2],
                    "bottom_points": bottom_values[0],
                    "bottom_advantages": bottom_values[1],
                    "bottom_penalties": bottom_values[2],
                },
                row_text,
            )
        return {}, row_text or cell_text

    def _parse_score(self, text: str) -> dict:
        rows = []
        for line in text.splitlines():
            row = self._score_row_values(line)
            if row:
                rows.append(row)
        if len(rows) >= 2:
            top_row, bottom_row = rows[-2], rows[-1]
            return {
                "top_points": top_row[0],
                "top_advantages": top_row[1],
                "top_penalties": top_row[2],
                "bottom_points": bottom_row[0],
                "bottom_advantages": bottom_row[1],
                "bottom_penalties": bottom_row[2],
            }

        fallback_values = []
        for token in re.findall(r"[0-9OoIl]{1,2}", text):
            value = self._score_token_value(token)
            if value is not None:
                fallback_values.append(value)
        if len(fallback_values) < 6:
            return {}
        digits = fallback_values[-6:]
        return {
            "top_points": digits[0],
            "top_advantages": digits[1],
            "top_penalties": digits[2],
            "bottom_points": digits[3],
            "bottom_advantages": digits[4],
            "bottom_penalties": digits[5],
        }

    def _clean_name_line(self, line: str) -> str | None:
        line = re.sub(r"[|_]+", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" -:")
        if not re.search(r"[A-Za-z]", line):
            return None
        if re.fullmatch(
            r"(?:P|PTS|POINTS|A|ADV|ADVANTAGES|PEN|PENALTIES|SCORE|TIME|TIMER)"
            r"(?:\s+|/|-|:)*",
            line,
            flags=re.IGNORECASE,
        ):
            return None
        return line

    def _parse_names(self, text: str) -> dict:
        if self.name_engine in (None, "none"):
            return {}

        score_row_pattern = re.compile(r"\b\d{1,2}\s+\d{1,2}\s+\d{1,2}\b")
        blocks = []
        current_block = []
        fallback_lines = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            score_match = score_row_pattern.search(line)
            name_part = line[: score_match.start()] if score_match else line
            cleaned_line = self._clean_name_line(name_part)
            if cleaned_line:
                current_block.append(cleaned_line)
                fallback_lines.append(cleaned_line)

            if score_match and current_block:
                blocks.append(current_block)
                current_block = []

        if current_block:
            blocks.append(current_block)

        if len(blocks) < 2 and len(fallback_lines) >= 2:
            midpoint = len(fallback_lines) // 2
            blocks = [fallback_lines[:midpoint], fallback_lines[midpoint:]]

        fields = {}
        if len(blocks) >= 1 and blocks[0]:
            fields["top_athlete_name"] = blocks[0][0]
        if len(blocks) >= 2 and blocks[1]:
            fields["bottom_athlete_name"] = blocks[1][0]
        return fields

    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        score = self._image_from_bytes(score_image)
        timer = self._image_from_bytes(timer_image)
        score_enabled = self.score_engine not in (None, "none")
        name_enabled = self.name_engine not in (None, "none")
        timer_text = self._ocr(timer, "--psm 7") if score_enabled else ""
        scoreboard_text = (
            self._ocr(score, "--psm 6") if score_enabled or name_enabled else ""
        )
        score_fields, score_grid_text = (
            self._parse_score_from_image(score) if score_enabled else ({}, "")
        )
        timer_state, timer_value = (
            self._parse_timer(timer_text) if score_enabled else (None, None)
        )
        if score_enabled and not score_fields:
            score_fields = self._parse_score(scoreboard_text)
        name_fields = self._parse_names(scoreboard_text) if name_enabled else {}
        return FrameReading(
            frame_second=frame_second,
            **score_fields,
            **name_fields,
            timer_state=timer_state,
            timer_value=timer_value,
            profile_id=self.parser_profile,
            score_engine=self.score_engine,
            name_engine=self.name_engine,
            evidence={
                "timer_text": timer_text,
                "scoreboard_text": scoreboard_text,
                "score_grid_text": score_grid_text,
            },
        )


def _load_app():
    import app as app_module

    return app_module.app


def log(message: str):
    timestamp = datetime.utcnow().isoformat(timespec="seconds")
    print(f"{timestamp}Z {message}", file=sys.stderr, flush=True)


def validate_ocr_engines(score_engine: str, name_engine: str | None):
    engines = [score_engine]
    if name_engine:
        engines.append(name_engine)
    for engine in engines:
        if engine not in SUPPORTED_ENGINES:
            raise RuntimeError(f"unsupported OCR engine: {engine}")
        if engine == "none":
            continue
        if engine == "tesseract":
            try:
                import pytesseract  # noqa: F401
                from PIL import Image  # noqa: F401
            except ImportError as exc:
                raise RuntimeError(
                    "tesseract engine requires pytesseract and pillow"
                ) from exc
            if not shutil.which("tesseract"):
                raise RuntimeError("tesseract engine requires the tesseract binary")
        if engine == "paddle":
            try:
                import paddleocr  # noqa: F401
            except ImportError as exc:
                raise RuntimeError("paddle engine requires paddleocr") from exc


def build_parser(parser_profile: str, score_engine: str, name_engine: str | None):
    if score_engine == "none" and name_engine in (None, "none"):
        return EmptyTextParser()
    return TesseractTextParser(parser_profile, score_engine, name_engine)


def event_payload(event):
    payload = asdict(event)
    payload["evidence"] = payload.pop("evidence")
    return payload


def provider_for_segment(segment, state, s3_client, bucket: str):
    capture_segments = getattr(segment, "archive_capture_segments", None)
    if capture_segments is None:
        capture_segments = state.capture_segments_for_archive(segment.archive_id)
    return S3FrameBatchProvider(capture_segments, s3_client, bucket)


def process_segment(segment, state, parser, s3_client, bucket: str):
    initial_state = state.initial_state_for_segment(segment)
    provider = provider_for_segment(segment, state, s3_client, bucket)
    interval = (
        getattr(getattr(segment, "scan", None), "coarse_interval_seconds", None)
        or DEFAULT_COARSE_INTERVAL_SECONDS
    )
    log(
        f"Scanning text segment id={segment.id} "
        f"archive_id={segment.archive_id} "
        f"range={segment.start_second}-{segment.end_second} "
        f"interval={interval}"
    )

    def debug_scan(message: str):
        log(f"Text scan segment id={segment.id}: {message}")

    events = scan_frame_text_segment(
        provider,
        parser,
        segment.start_second,
        segment.end_second,
        initial_state=initial_state,
        coarse_interval_seconds=interval,
        debug_callback=debug_scan,
    )
    state.mark_success(segment, events)
    log(f"Text scan segment success id={segment.id} events={len(events)}")


def run(args, state=None) -> int:
    validate_ocr_engines(args.score_engine, args.name_engine)
    parser = build_parser(args.parser_profile, args.score_engine, args.name_engine)
    if state is None:
        state = LocalTextScanState()
    if not bucket_name:
        raise RuntimeError("S3_BUCKET is not configured")
    s3_client = get_s3_client()

    processed = 0
    while processed < args.max_segments:
        scan_id = uuid.UUID(args.scan_id) if args.scan_id else None
        archive_id = uuid.UUID(args.archive_id) if args.archive_id else None
        background_task_id = (
            uuid.UUID(args.background_task_id) if args.background_task_id else None
        )
        segment = state.claim_next_segment(
            scan_id=scan_id,
            archive_id=archive_id,
            youtube_video_id=args.youtube_id,
            background_task_id=background_task_id,
        )
        if not segment:
            print("No claimable livestream frame text scan segments.")
            return 0

        try:
            process_segment(segment, state, parser, s3_client, bucket_name)
            processed += 1
        except Exception as exc:
            state.mark_error(segment, str(exc))
            print(f"Text scan segment {segment.id} failed: {exc}", file=sys.stderr)
            return 1

        if not args.claim_next:
            return 0
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-id")
    parser.add_argument("--archive-id")
    parser.add_argument("--youtube-id")
    parser.add_argument("--claim-next", action="store_true")
    parser.add_argument("--max-segments", type=int, default=1)
    parser.add_argument("--parser-profile", default=DEFAULT_PARSER_PROFILE)
    parser.add_argument("--score-engine", default=DEFAULT_SCORE_ENGINE)
    parser.add_argument("--name-engine", default=DEFAULT_NAME_ENGINE)
    parser.add_argument("--background-task-id")
    parser.add_argument(
        "--admin-url",
        default=os.environ.get(ADMIN_URL_ENV_VAR),
        help=(
            "Admin app base URL for REST-backed state, defaults to "
            f"${ADMIN_URL_ENV_VAR}"
        ),
    )
    parser.add_argument(
        "--admin-password",
        default=(
            os.environ.get(ADMIN_PASSWORD_ENV_VAR) or os.environ.get("ADMIN_PASSWORD")
        ),
        help=(
            "Admin password for REST-backed state, defaults to "
            f"${ADMIN_PASSWORD_ENV_VAR} or $ADMIN_PASSWORD"
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.admin_url:
        if not args.admin_password:
            print(
                "--admin-password or LIVESTREAM_ARCHIVE_ADMIN_PASSWORD is required "
                "when --admin-url is set",
                file=sys.stderr,
            )
            return 2
        return run(args, AdminApiTextScanState(args.admin_url, args.admin_password))

    app = _load_app()
    with app.app_context():
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
