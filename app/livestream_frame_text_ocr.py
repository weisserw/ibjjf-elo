from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from livestream_frame_text_scan import (
    FrameReading,
    SCOREBOARD_STATE_BLANK,
    SCOREBOARD_STATE_VISIBLE,
)

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError:  # pragma: no cover - validated before worker scans run.
    cv2 = None
    np = None
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageOps = None


SUPPORTED_SCORE_ENGINES = ("none", "fixed_digit")
SUPPORTED_NAME_ENGINES = ("none", "tesseract")
SCORE_TEMPLATE_SIZE = (24, 36)
TIMER_TEMPLATE_SIZE = (28, 48)
NAME_COLUMN_RIGHT_RATIO = 0.481
NAME_RENDERED_COLUMN_RIGHT_RATIO = 0.52
NAME_ROW_Y_EDGES = (0.0, 0.431, 0.861)
NAME_LINE_TOP_RATIO = 0.02
NAME_LINE_BOTTOM_RATIO = 0.42
NAME_OCR_SCALE = 3


class EmptyTextParser:
    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        return FrameReading(frame_second=frame_second, score_engine="none")


@dataclass(frozen=True)
class DigitTemplate:
    digit: int
    mask: int
    pixel_count: int
    source: str


@dataclass(frozen=True)
class DigitPrediction:
    digit: int | None
    similarity: float
    source: str


@dataclass(frozen=True)
class ScoreLayout:
    name: str
    cell_boxes: tuple[tuple[int, int, int, int], ...]
    background_roles: tuple[str, ...]


@dataclass(frozen=True)
class ScoreboardDigitReading:
    digits: tuple[int, int, int, int, int, int] | None
    predictions: tuple[DigitPrediction, ...]
    has_layout: bool


@dataclass(frozen=True)
class TimerDigitReading:
    state: str | None
    value: str | None
    predictions: tuple[DigitPrediction, ...]


def _require_fixed_digit_dependencies():
    if (
        cv2 is None
        or np is None
        or Image is None
        or ImageDraw is None
        or ImageFont is None
    ):
        raise RuntimeError(
            "fixed_digit score engine requires opencv-python, numpy, and pillow"
        )


def _score_cell_boxes(
    image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    width, height = image_size
    x_edges = (0.481, 0.638, 0.791, 0.919)
    y_edges = (0.0, 0.431, 0.861)
    return tuple(
        (
            int(width * x_edges[col]),
            int(height * y_edges[row]),
            int(width * x_edges[col + 1]),
            int(height * y_edges[row + 1]),
        )
        for row in range(2)
        for col in range(3)
    )


def _rendered_score_cell_boxes(
    image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    width, height = image_size
    x_ranges = ((0.568, 0.671), (0.675, 0.777), (0.779, 0.883))
    y_ranges = ((0.074, 0.403), (0.440, 0.773))
    return tuple(
        (
            int(width * x_start),
            int(height * y_start),
            int(width * x_end),
            int(height * y_end),
        )
        for y_start, y_end in y_ranges
        for x_start, x_end in x_ranges
    )


def _score_layouts(image_size: tuple[int, int]) -> tuple[ScoreLayout, ...]:
    return (
        ScoreLayout(
            "legacy",
            _score_cell_boxes(image_size),
            ("green", "green", "red", "green", "green", "red"),
        ),
        ScoreLayout(
            "rendered",
            _rendered_score_cell_boxes(image_size),
            ("green", "yellow", "red", "green", "yellow", "red"),
        ),
    )


def _name_line_boxes(
    image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    width, height = image_size
    right = int(width * NAME_COLUMN_RIGHT_RATIO)
    boxes = []
    for row in range(2):
        row_top = int(height * NAME_ROW_Y_EDGES[row])
        row_bottom = int(height * NAME_ROW_Y_EDGES[row + 1])
        row_height = row_bottom - row_top
        top = row_top + int(row_height * NAME_LINE_TOP_RATIO)
        bottom = row_top + int(row_height * NAME_LINE_BOTTOM_RATIO)
        boxes.append((0, top, right, max(top + 1, bottom)))
    return tuple(boxes)


def _name_column_box(image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = image_size
    return (
        0,
        0,
        int(width * NAME_COLUMN_RIGHT_RATIO),
        int(height * NAME_ROW_Y_EDGES[-1]),
    )


def _name_column_boxes(
    image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    width, height = image_size
    boxes = [_name_column_box(image_size)]
    if width >= 400:
        boxes.insert(
            0,
            (
                0,
                0,
                int(width * NAME_RENDERED_COLUMN_RIGHT_RATIO),
                int(height * NAME_ROW_Y_EDGES[-1]),
            ),
        )
    return tuple(boxes)


def _inner_cell(image):
    margin = max(2, min(image.size) // 12)
    return image.crop((margin, margin, image.width - margin, image.height - margin))


def _score_cell_has_background(image, role: str) -> bool:
    rgb = np.asarray(image.convert("RGB"))
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    if role == "red":
        mask = (red > 120) & (green < 110) & (blue < 130)
    elif role == "yellow":
        mask = (red > 150) & (green > 110) & (blue < 120)
    else:
        mask = (green > 100) & (blue < 150) & (red < 190)
    return bool(mask.mean() >= 0.12)


def _score_digit_threshold(image):
    rgb = np.asarray(image.convert("RGB"))
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    spread = np.maximum.reduce([red, green, blue]) - np.minimum.reduce(
        [red, green, blue]
    )
    return (red > 145) & (green > 145) & (blue > 95) & (spread < 120)


def _largest_component(mask, min_area: int):
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype("uint8"), 8
    )
    if component_count <= 1:
        return None
    areas = stats[1:, cv2.CC_STAT_AREA]
    component_index = 1 + int(np.argmax(areas))
    if int(areas.max()) < min_area:
        return None
    x, y, width, height, _ = stats[component_index]
    return labels[y : y + height, x : x + width] == component_index


def _normalize_mask(mask, size: tuple[int, int]):
    image = Image.fromarray(mask.astype("uint8") * 255, "L")
    return np.asarray(image.resize(size, Image.Resampling.NEAREST)) > 0


def _score_digit_mask(image):
    threshold = _score_digit_threshold(image)
    component = _largest_component(threshold, min_area=20)
    if component is None:
        return None
    return _normalize_mask(component, SCORE_TEMPLATE_SIZE)


def _font_paths() -> tuple[str, ...]:
    return (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )


def _render_digit_template(digit: int, font, size: tuple[int, int]):
    canvas = Image.new("L", (140, 140), 0)
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), str(digit), font=font)
    draw.text((10 - bbox[0], 10 - bbox[1]), str(digit), font=font, fill=255)
    glyph_box = canvas.getbbox()
    if glyph_box is None:
        return None
    return np.asarray(canvas.crop(glyph_box).resize(size, Image.Resampling.NEAREST)) > 0


def _pack_mask(mask) -> tuple[int, int]:
    flat = np.ascontiguousarray(mask.reshape(-1), dtype=np.uint8)
    packed_bytes = np.packbits(flat, bitorder="little").tobytes()
    return int.from_bytes(packed_bytes, "little"), int(flat.sum())


def _generated_templates(
    size: tuple[int, int], font_sizes: range, source_prefix: str
) -> list[DigitTemplate]:
    _require_fixed_digit_dependencies()
    templates = []
    for font_path in _font_paths():
        for font_size in font_sizes:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except OSError:
                continue
            for digit in range(10):
                mask = _render_digit_template(digit, font, size)
                if mask is None:
                    continue
                packed, pixel_count = _pack_mask(mask)
                templates.append(
                    DigitTemplate(
                        digit,
                        packed,
                        pixel_count,
                        f"{source_prefix}:{Path(font_path).name}:{font_size}",
                    )
                )
    if templates:
        return templates

    font = ImageFont.load_default()
    for digit in range(10):
        mask = _render_digit_template(digit, font, size)
        if mask is None:
            continue
        packed, pixel_count = _pack_mask(mask)
        templates.append(
            DigitTemplate(digit, packed, pixel_count, f"{source_prefix}:default")
        )
    return templates


def _packed_jaccard(mask: int, pixel_count: int, template: DigitTemplate) -> float:
    intersection = (mask & template.mask).bit_count()
    union = pixel_count + template.pixel_count - intersection
    return float(intersection / union) if union else 0.0


class FixedDigitClassifier:
    def __init__(
        self,
        size: tuple[int, int],
        font_sizes: range,
        source_prefix: str,
        templates: list[DigitTemplate] | None = None,
    ):
        self.size = size
        self.templates = templates or _generated_templates(
            size, font_sizes, source_prefix
        )

    def predict(self, mask) -> DigitPrediction:
        packed, pixel_count = _pack_mask(mask)
        best_digit = None
        best_similarity = 0.0
        best_source = "none"
        for template in self.templates:
            similarity = _packed_jaccard(packed, pixel_count, template)
            if similarity > best_similarity:
                best_digit = template.digit
                best_similarity = similarity
                best_source = template.source
        return DigitPrediction(best_digit, best_similarity, best_source)


class ScoreboardDigitReader:
    def __init__(self, classifier: FixedDigitClassifier | None = None):
        self.classifier = classifier or FixedDigitClassifier(
            SCORE_TEMPLATE_SIZE, range(28, 50, 4), "score-font"
        )

    def read(self, image) -> ScoreboardDigitReading:
        if image is None:
            return ScoreboardDigitReading(None, (), False)

        readings = [
            self._read_layout(image, layout) for layout in _score_layouts(image.size)
        ]
        readings_with_digits = [
            reading for reading in readings if reading.has_layout and reading.digits
        ]
        if readings_with_digits:
            return max(readings_with_digits, key=self._reading_confidence)

        readings_with_layout = [reading for reading in readings if reading.has_layout]
        if readings_with_layout:
            return max(readings_with_layout, key=self._reading_confidence)

        return readings[0]

    def _read_layout(self, image, layout: ScoreLayout) -> ScoreboardDigitReading:
        predictions = []
        has_layout = True
        for box, role in zip(layout.cell_boxes, layout.background_roles):
            cell = _inner_cell(image.crop(box))
            if not _score_cell_has_background(cell, role):
                has_layout = False
            mask = _score_digit_mask(cell)
            if mask is None:
                predictions.append(DigitPrediction(None, 0.0, "none"))
            else:
                predictions.append(self.classifier.predict(mask))
        if not has_layout or any(
            prediction.digit is None for prediction in predictions
        ):
            return ScoreboardDigitReading(None, tuple(predictions), has_layout)
        return ScoreboardDigitReading(
            tuple(prediction.digit for prediction in predictions),
            tuple(predictions),
            True,
        )

    @staticmethod
    def _reading_confidence(reading: ScoreboardDigitReading) -> float:
        if not reading.predictions:
            return 0.0
        return float(
            sum(prediction.similarity for prediction in reading.predictions)
            / len(reading.predictions)
        )


class TimerDigitReader:
    def __init__(self, classifier: FixedDigitClassifier | None = None):
        self.classifier = classifier or FixedDigitClassifier(
            TIMER_TEMPLATE_SIZE, range(44, 73, 4), "timer-font"
        )

    def _state(self, image) -> str | None:
        if image is None:
            return None
        rgb = np.asarray(image.convert("RGB"))
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        red_background = ((red > 130) & (green < 100) & (blue < 120)).mean()
        green_foreground = (
            (green > 140) & (red < 120) & (blue < 140) & ((green - red) > 40)
        ).mean()
        orange_foreground = (
            (red > 150)
            & (green > 90)
            & (green < 190)
            & (blue < 120)
            & ((red - green) > 20)
        ).mean()
        white_foreground = ((red > 180) & (green > 180) & (blue > 180)).mean()
        dark_background = ((red < 60) & (green < 60) & (blue < 60)).mean()
        dark_blue_background = ((blue > 60) & (red < 60) & (green < 80)).mean()
        if red_background > 0.25:
            return "stopped"
        if white_foreground > 0.03 and dark_blue_background > 0.15:
            return "stopped"
        if green_foreground > 0.03 and dark_background > 0.30:
            return "running"
        if (
            green_foreground > 0.03 or orange_foreground > 0.03
        ) and dark_blue_background > 0.15:
            return "running"
        return "blank"

    def _threshold(self, image, state: str):
        rgb = np.asarray(image.convert("RGB"))
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        if state == "stopped":
            red_background = ((red > 130) & (green < 100) & (blue < 120)).mean()
            if red_background > 0.25:
                return (red < 70) & (green < 70) & (blue < 70)
            return (red > 180) & (green > 180) & (blue > 180)
        green_digits = (green > 110) & (red < 120) & (blue < 130) & ((green - red) > 40)
        orange_digits = (
            (red > 150)
            & (green > 90)
            & (green < 190)
            & (blue < 120)
            & ((red - green) > 20)
        )
        return green_digits | orange_digits

    @staticmethod
    def _looks_like_timer_six(mask) -> bool:
        return bool(
            mask[:14, 18:].mean() < 0.40
            and mask[:10, :].mean() < 0.50
            and mask[16:30, :].mean() > 0.60
        )

    def _predict_digit(self, mask) -> DigitPrediction:
        prediction = self.classifier.predict(mask)
        if prediction.digit == 0 and self._looks_like_timer_six(mask):
            return DigitPrediction(
                6,
                prediction.similarity,
                f"{prediction.source}:timer-six-shape",
            )
        return prediction

    def read(self, image) -> TimerDigitReading:
        state = self._state(image)
        if image is None or state in (None, "blank"):
            return TimerDigitReading(state, None, ())

        full_threshold = self._threshold(image, state)
        width, height = image.size
        display_left = int(width * 0.10)
        display_right = int(width * 0.88)
        display_bottom = int(height * 0.80)
        display_mask = full_threshold[:display_bottom, display_left:display_right]
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
            display_mask.astype("uint8"), 8
        )

        components = []
        for component_index in range(1, component_count):
            x, y, component_width, component_height, area = stats[component_index]
            if area < 40 or component_height < 20 or component_width < 8:
                continue
            components.append(
                (
                    int(x + display_left),
                    int(y),
                    int(component_width),
                    int(component_height),
                    int(component_index),
                )
            )
        components.sort(key=lambda item: item[0])

        predictions = []
        for x, y, component_width, component_height, component_index in components:
            component_mask = (
                labels[
                    y : y + component_height,
                    x - display_left : x - display_left + component_width,
                ]
                == component_index
            )
            normalized = _normalize_mask(component_mask, TIMER_TEMPLATE_SIZE)
            predictions.append(self._predict_digit(normalized))

        digits = [
            prediction.digit
            for prediction in predictions
            if prediction.digit is not None
        ]
        if len(digits) == 3:
            value = f"{digits[0]}:{digits[1]}{digits[2]}"
        elif len(digits) == 4:
            minutes = digits[0] * 10 + digits[1]
            value = f"{minutes}:{digits[2]}{digits[3]}"
        else:
            value = None
        return TimerDigitReading(state, value, tuple(predictions))


class FrameImageTextParser:
    def __init__(self, parser_profile: str, score_engine: str, name_engine: str | None):
        self.parser_profile = parser_profile
        self.score_engine = score_engine
        self.name_engine = name_engine
        score_enabled = score_engine not in (None, "none")
        self.score_reader = ScoreboardDigitReader() if score_enabled else None
        self.timer_reader = TimerDigitReader() if score_enabled else None
        if name_engine not in (None, "none"):
            import pytesseract  # noqa: F401

    def _image_from_bytes(self, image_bytes):
        if not image_bytes:
            return None
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def _ocr(self, image, config: str = "") -> str:
        if image is None:
            return ""
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip()

    def _prepare_name_ocr_image(self, image):
        if image is None:
            return None
        if Image is None or ImageOps is None:
            return image

        prepared = ImageOps.autocontrast(ImageOps.grayscale(image))
        return prepared.resize(
            (prepared.width * NAME_OCR_SCALE, prepared.height * NAME_OCR_SCALE),
            Image.Resampling.LANCZOS,
        )

    def _name_from_row_text(self, text: str) -> str | None:
        for raw_line in text.splitlines():
            cleaned_line = self._clean_name_line(raw_line)
            if cleaned_line:
                return cleaned_line
        return None

    def _complete_athlete_name_fields(self, fields: dict) -> dict:
        if fields.get("top_athlete_name") == "Victory" and fields.get(
            "bottom_athlete_name"
        ):
            complete_fields = {
                "top_athlete_name": "Victory",
                "bottom_athlete_name": fields["bottom_athlete_name"],
            }
            if fields.get("bottom_team_name"):
                complete_fields["bottom_team_name"] = fields["bottom_team_name"]
            return complete_fields
        if fields.get("top_athlete_name") and fields.get("bottom_athlete_name"):
            return {
                "top_athlete_name": fields["top_athlete_name"],
                "bottom_athlete_name": fields["bottom_athlete_name"],
            }
        return {}

    def _ocr_name_fields(self, score_image) -> tuple[str, dict]:
        if score_image is None:
            return "", {}
        if not hasattr(score_image, "crop") or not hasattr(score_image, "size"):
            text = self._ocr(score_image, "--psm 6")
            return text, self._complete_athlete_name_fields(self._parse_names(text))

        column_text = ""
        column_fields = {}
        column_boxes = _name_column_boxes(score_image.size)
        for index, box in enumerate(column_boxes):
            column_image = self._prepare_name_ocr_image(score_image.crop(box))
            column_text = self._ocr(column_image, "--psm 6")
            victory_fields = self._complete_athlete_name_fields(
                self._parse_victory_names(column_text)
            )
            if victory_fields:
                return column_text, victory_fields

            parsed_column_fields = self._complete_athlete_name_fields(
                self._parse_names(column_text, allow_two_line_fallback=False)
            )
            if parsed_column_fields and len(column_boxes) > 1 and index == 0:
                return column_text, parsed_column_fields
            if parsed_column_fields:
                column_fields = parsed_column_fields

        if column_fields and len(column_boxes) > 1:
            return column_text, column_fields

        row_fields = {}
        row_texts = []
        for field_name, box in zip(
            ("top_athlete_name", "bottom_athlete_name"),
            _name_line_boxes(score_image.size),
        ):
            name_image = self._prepare_name_ocr_image(score_image.crop(box))
            row_text = self._ocr(name_image, "--psm 7")
            if row_text:
                row_texts.append(row_text)
            name = self._name_from_row_text(row_text)
            if name:
                row_fields[field_name] = name
        text = "\n".join([column_text, *row_texts]).strip()
        fields = self._complete_athlete_name_fields(row_fields)
        if fields:
            return text, fields

        return text, column_fields

    def _clean_text_line(self, line: str) -> str | None:
        line = re.sub(r"[|_]+", " ", line)
        tokens = []
        for token in line.split():
            if re.search(r"\d", token):
                break
            if not re.match(r"^[^\W\d_](?:[^\W\d_]|['.,:-])*$", token):
                continue
            tokens.append(token)
        line = " ".join(tokens)
        line = re.sub(r"\s+", " ", line).strip(" -:")
        line = line.strip(" -:.,'")
        if not re.search(r"[^\W\d_]", line):
            return None
        if re.fullmatch(
            r"(?:P|PTS|POINTS|A|ADV|ADVANTAGES|PEN|PENALTIES|SCORE|TIME|TIMER)"
            r"(?:\s+|/|-|:)*",
            line,
            flags=re.IGNORECASE,
        ):
            return None
        alpha_tokens = line.split()
        total_letters = sum(
            len(re.sub(r"[^\w]|[\d_]", "", token)) for token in alpha_tokens
        )
        if total_letters < 6:
            return None
        return line

    def _clean_name_line(self, line: str) -> str | None:
        line = self._clean_text_line(line)
        if line is None:
            return None
        alpha_tokens = line.split()
        substantial_tokens = [
            token
            for token in alpha_tokens
            if len(re.sub(r"[^\w]|[\d_]", "", token)) >= 2
        ]
        if len(substantial_tokens) < 2:
            return None
        return line

    def _is_victory_line(self, line: str) -> bool:
        letters = re.sub(r"[^A-Za-z]", "", line).lower()
        return letters == "victory" or letters == "ictory"

    def _parse_victory_names(self, text: str) -> dict:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if not self._is_victory_line(line):
                continue

            content_lines = []
            for raw_line in lines[index + 1 :]:
                cleaned_line = self._clean_name_line(raw_line)
                if cleaned_line:
                    content_lines.append(cleaned_line)
                if len(content_lines) >= 2:
                    break

            if content_lines:
                fields = {
                    "top_athlete_name": "Victory",
                    "bottom_athlete_name": content_lines[0],
                }
                if len(content_lines) >= 2:
                    fields["bottom_team_name"] = content_lines[1]
                return fields
        return {}

    @staticmethod
    def _athlete_team_line_fields(lines: list[str]) -> dict:
        if len(lines) < 4:
            return {}
        return {
            "top_athlete_name": lines[0],
            "bottom_athlete_name": lines[2],
        }

    def _parse_names(self, text: str, *, allow_two_line_fallback: bool = True) -> dict:
        if self.name_engine in (None, "none"):
            return {}

        victory_fields = self._parse_victory_names(text)
        if victory_fields:
            return victory_fields

        score_row_pattern = re.compile(r"\b\d{1,2}\s+\d{1,2}\s+\d{1,2}\b")
        blocks = []
        current_block = []
        fallback_lines = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
                continue

            score_match = score_row_pattern.search(line)
            name_part = line[: score_match.start()] if score_match else line
            cleaned_line = self._clean_text_line(name_part)
            if cleaned_line:
                current_block.append(cleaned_line)
                fallback_lines.append(cleaned_line)

            if score_match and current_block:
                blocks.append(current_block)
                current_block = []

        if current_block:
            blocks.append(current_block)

        athlete_team_fields = self._athlete_team_line_fields(fallback_lines)
        if athlete_team_fields:
            return athlete_team_fields

        if len(blocks) < 2 and len(fallback_lines) >= 2:
            if not allow_two_line_fallback and len(fallback_lines) < 4:
                return {}
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
        if name_enabled:
            scoreboard_text, name_fields = self._ocr_name_fields(score)
        else:
            scoreboard_text, name_fields = "", {}
        score_reading = self.score_reader.read(score) if self.score_reader else None
        timer_reading = self.timer_reader.read(timer) if self.timer_reader else None
        score_fields = score_fields_from_reading(score_reading) if score_enabled else {}
        timer_state = timer_reading.state if timer_reading else None
        timer_value = timer_reading.value if timer_reading else None
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
                "scoreboard_text": scoreboard_text,
                "score_digits": score_digits_text(score_reading),
                "score_digit_similarities": score_digit_similarities(score_reading),
                "timer_digit_similarities": timer_digit_similarities(timer_reading),
            },
        )


TesseractTextParser = FrameImageTextParser


def score_fields_from_reading(reading: ScoreboardDigitReading | None) -> dict:
    if reading is None:
        return {}
    if reading.digits is None:
        if reading.predictions and not reading.has_layout:
            return {"scoreboard_state": SCOREBOARD_STATE_BLANK}
        return {}
    return {
        "scoreboard_state": SCOREBOARD_STATE_VISIBLE,
        "top_points": reading.digits[0],
        "top_advantages": reading.digits[1],
        "top_penalties": reading.digits[2],
        "bottom_points": reading.digits[3],
        "bottom_advantages": reading.digits[4],
        "bottom_penalties": reading.digits[5],
    }


def score_digits_text(reading: ScoreboardDigitReading | None) -> str:
    if reading is None or reading.digits is None:
        return ""
    digits = "".join(str(digit) for digit in reading.digits)
    return f"{digits[:3]}/{digits[3:]}"


def score_digit_similarities(reading: ScoreboardDigitReading | None) -> list[float]:
    if reading is None:
        return []
    return [round(prediction.similarity, 4) for prediction in reading.predictions]


def timer_digit_similarities(reading: TimerDigitReading | None) -> list[float]:
    if reading is None:
        return []
    return [round(prediction.similarity, 4) for prediction in reading.predictions]


def validate_ocr_engines(score_engine: str, name_engine: str | None):
    if score_engine not in SUPPORTED_SCORE_ENGINES:
        raise RuntimeError(f"unsupported score engine: {score_engine}")
    if score_engine == "fixed_digit":
        _require_fixed_digit_dependencies()

    if name_engine is not None and name_engine not in SUPPORTED_NAME_ENGINES:
        raise RuntimeError(f"unsupported name engine: {name_engine}")
    if name_engine == "tesseract":
        try:
            import pytesseract  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "tesseract name engine requires pytesseract and pillow"
            ) from exc
        if Image is None:
            raise RuntimeError("tesseract name engine requires pytesseract and pillow")
        if not shutil.which("tesseract"):
            raise RuntimeError("tesseract name engine requires the tesseract binary")


def build_parser(parser_profile: str, score_engine: str, name_engine: str | None):
    if score_engine == "none" and name_engine in (None, "none"):
        return EmptyTextParser()
    return FrameImageTextParser(parser_profile, score_engine, name_engine)
