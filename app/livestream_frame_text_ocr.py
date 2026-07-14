from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from livestream_frame_text_scan import (
    FrameReading,
    SCOREBOARD_STATE_BLANK,
    SCOREBOARD_STATE_VISIBLE,
)

_VISION_IMPORT_ERROR = None

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont, ImageOps
except ImportError as exc:  # pragma: no cover - validated before worker scans run.
    cv2 = None
    np = None
    Image = None
    ImageDraw = None
    ImageFont = None
    ImageOps = None
    _VISION_IMPORT_ERROR = exc


SUPPORTED_SCORE_ENGINES = ("none", "fixed_digit")
SUPPORTED_NAME_ENGINES = ("none", "tesseract", "paddle")
SCORE_TEMPLATE_SIZE = (24, 36)
TIMER_TEMPLATE_SIZE = (28, 48)
SCORE_THREE_EIGHT_SIMILARITY_MARGIN = 0.02
SCORE_THREE_MIN_RIGHT_DENSITY = 0.58
SCORE_BORDER_COLUMN_MIN_DENSITY = 0.85
OCR_FONT_DIR = Path(__file__).resolve().parent / "ocr_fonts"
NAME_COLUMN_RIGHT_RATIO = 0.481
NAME_RENDERED_COLUMN_RIGHT_RATIO = 0.52
NAME_ROW_Y_EDGES = (0.0, 0.431, 0.861)
NAME_LINE_TOP_RATIO = 0.02
NAME_LINE_BOTTOM_RATIO = 0.42
NAME_OCR_SCALE = 3
PADDLE_ROW_NAME_RETRY_SCALE = 4
PADDLE_DIRECT_ROW_MIN_WIDTH = 170
PADDLE_DIRECT_ROW_MAX_HEIGHT = 100


def _configure_paddle_runtime():
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("FLAGS_use_onednn", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("OMP_NUM_THREADS", "1")


class EmptyTextParser:
    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        return FrameReading(frame_second=frame_second, score_engine="none")

    def parse_score_timer(
        self, frame_second: int, score_image, timer_image
    ) -> FrameReading:
        return self.parse(frame_second, score_image, timer_image)


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
class ScoreDigitMask:
    mask: object
    x: int
    width: int
    image_width: int


@dataclass(frozen=True)
class TimerDigitReading:
    state: str | None
    value: str | None
    predictions: tuple[DigitPrediction, ...]


@dataclass(frozen=True)
class PaddleTextItem:
    text: str
    confidence: float | None
    box: tuple[float, float, float, float] | None = None


def _require_fixed_digit_dependencies():
    if (
        cv2 is None
        or np is None
        or Image is None
        or ImageDraw is None
        or ImageFont is None
    ):
        message = "fixed_digit score engine requires opencv-python, numpy, and pillow"
        if _VISION_IMPORT_ERROR is not None:
            message = f"{message}; import error: {_VISION_IMPORT_ERROR}"
        raise RuntimeError(message)


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


def _compact_rendered_score_cell_boxes(
    image_size: tuple[int, int]
) -> tuple[tuple[int, int, int, int], ...]:
    width, height = image_size
    x_ranges = ((0.541, 0.709), (0.709, 0.884), (0.884, 1.0))
    y_ranges = ((0.0, 0.436), (0.487, 0.923))
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


def _score_role_component_boxes(image, role: str):
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

    component_count, _, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype("uint8"), 8
    )
    min_area = max(80, int(image.width * image.height * 0.008))
    boxes = []
    for component_index in range(1, component_count):
        x, y, width, height, area = stats[component_index]
        if int(area) < min_area:
            continue
        boxes.append((int(x), int(y), int(x + width), int(y + height), int(area)))
    return tuple(boxes)


def _component_vertical_overlap(first, second) -> float:
    overlap = max(0, min(first[3], second[3]) - max(first[1], second[1]))
    min_height = max(1, min(first[3] - first[1], second[3] - second[1]))
    return overlap / min_height


def _row_vertical_overlap(first, second) -> float:
    overlap = max(0, min(first[1], second[1]) - max(first[0], second[0]))
    min_height = max(1, min(first[1] - first[0], second[1] - second[0]))
    return overlap / min_height


def _row_x_edge_delta(first, second) -> int:
    return max(
        abs(first_edge - second_edge)
        for first_edge, second_edge in zip(first[2], second[2])
    )


def _detected_rendered_score_cell_boxes(image):
    yellow_boxes = _score_role_component_boxes(image, "yellow")
    red_boxes = _score_role_component_boxes(image, "red")
    row_pairs = []
    for yellow_box in yellow_boxes:
        candidates = []
        for red_box in red_boxes:
            overlap = _component_vertical_overlap(yellow_box, red_box)
            column_width = red_box[0] - yellow_box[0]
            edge_gap = red_box[0] - yellow_box[2]
            if overlap < 0.45 or column_width <= 0 or not -6 <= edge_gap <= 10:
                continue
            candidates.append((overlap, -abs(edge_gap), red_box))
        if not candidates:
            continue
        _, _, red_box = max(candidates)
        column_width = red_box[0] - yellow_box[0]
        x_edges = (
            max(0, yellow_box[0] - column_width),
            yellow_box[0],
            red_box[0],
            red_box[2],
        )
        y_start = min(yellow_box[1], red_box[1])
        y_end = max(yellow_box[3], red_box[3])
        area = yellow_box[4] + red_box[4]
        row_pairs.append((y_start, y_end, x_edges, area))

    max_x_edge_delta = max(8, int(image.width * 0.05))
    best_rows = None
    best_score = None
    for first_index, first in enumerate(row_pairs):
        for second in row_pairs[first_index + 1 :]:
            if _row_vertical_overlap(first, second) > 0.45:
                continue
            x_edge_delta = _row_x_edge_delta(first, second)
            if x_edge_delta > max_x_edge_delta:
                continue
            score = first[3] + second[3] - x_edge_delta
            if best_score is None or score > best_score:
                best_rows = (first, second)
                best_score = score
    if best_rows is None:
        return ()

    boxes = []
    min_cell_width = max(4, int(image.width * 0.02))
    min_cell_height = max(4, int(image.height * 0.08))
    for y_start, y_end, x_edges, _ in sorted(best_rows, key=lambda item: item[0]):
        if y_end - y_start < min_cell_height:
            return ()
        for col in range(3):
            if x_edges[col + 1] - x_edges[col] < min_cell_width:
                return ()
            boxes.append((x_edges[col], y_start, x_edges[col + 1], y_end))
    return tuple(boxes)


def _score_layouts(image_size: tuple[int, int]) -> tuple[ScoreLayout, ...]:
    layouts = [
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
    ]
    if image_size[0] < 240:
        layouts.append(
            ScoreLayout(
                "compact_rendered",
                _compact_rendered_score_cell_boxes(image_size),
                ("green", "yellow", "red", "green", "yellow", "red"),
            )
        )
    return tuple(layouts)


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
    if width >= 400 or width < 240:
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
    if image.width <= margin * 2 or image.height <= margin * 2:
        return image
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


def _digit_components(mask, min_area: int):
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype("uint8"), 8
    )
    components = []
    for component_index in range(1, component_count):
        x, y, width, height, area = stats[component_index]
        if int(area) < min_area:
            continue
        components.append((int(x), int(y), int(width), int(height), component_index))
    components.sort(key=lambda item: item[0])
    return tuple(components), labels


def _normalize_mask(mask, size: tuple[int, int]):
    image = Image.fromarray(mask.astype("uint8") * 255, "L")
    return np.asarray(image.resize(size, Image.Resampling.NEAREST)) > 0


def _score_digit_mask(image):
    threshold = _score_digit_threshold(image)
    component = _largest_component(threshold, min_area=20)
    if component is None:
        return None
    return _normalize_mask(component, SCORE_TEMPLATE_SIZE)


def _score_digit_masks(image):
    return tuple(entry.mask for entry in _score_digit_mask_entries(image))


def _score_digit_mask_entries(image):
    threshold = _score_digit_threshold(image)
    # Tight scoreboard crops can include a nearly solid vertical separator
    # connected to the final digit. Remove the separator without discarding
    # the digit component attached to it.
    border_columns = threshold.mean(axis=0) >= SCORE_BORDER_COLUMN_MIN_DENSITY
    threshold[:, border_columns] = False
    components, labels = _digit_components(threshold, min_area=20)
    min_height = max(8, int(image.height * 0.35))
    min_width = max(4, int(image.width * 0.12))
    candidates = []
    for x, y, width, height, component_index in components:
        if height < min_height or width < min_width:
            continue
        # JPEG resampling can leave a one-pixel gap between a crop-boundary
        # stripe and the actual image edge.
        touches_edge = x == 0 or x + width >= image.width - 1
        candidates.append((x, y, width, height, component_index, touches_edge))

    has_interior_candidate = any(not candidate[-1] for candidate in candidates)
    masks = []
    for x, y, width, height, component_index, touches_edge in candidates:
        if touches_edge:
            if not has_interior_candidate:
                continue
            if height >= int(image.height * 0.85) or width >= int(image.width * 0.55):
                continue
        component_mask = labels[y : y + height, x : x + width] == component_index
        masks.append(
            ScoreDigitMask(
                _normalize_mask(component_mask, SCORE_TEMPLATE_SIZE),
                x,
                width,
                image.width,
            )
        )
    return tuple(masks)


def _font_paths() -> tuple[str, ...]:
    return tuple(str(path) for path in sorted(OCR_FONT_DIR.glob("*.ttf")))


def _render_digit_template(digit: int, font, size: tuple[int, int]):
    canvas = Image.new("L", (140, 140), 0)
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), str(digit), font=font)
    draw.text((10 - bbox[0], 10 - bbox[1]), str(digit), font=font, fill=255)
    glyph_box = canvas.getbbox()
    if glyph_box is None:
        return None
    return np.asarray(canvas.crop(glyph_box).resize(size, Image.Resampling.NEAREST)) > 0


def _top_cropped_template_masks(mask, size: tuple[int, int]):
    return tuple(
        (
            ratio,
            _normalize_mask(mask[max(1, int(size[1] * ratio)) :, :], size),
        )
        for ratio in (0.08, 0.12, 0.16, 0.20)
    )


def _pack_mask(mask) -> tuple[int, int]:
    flat = np.ascontiguousarray(mask.reshape(-1), dtype=np.uint8)
    packed_bytes = np.packbits(flat, bitorder="little").tobytes()
    return int.from_bytes(packed_bytes, "little"), int(flat.sum())


def _generated_templates(
    size: tuple[int, int],
    font_sizes: range,
    source_prefix: str,
    include_top_crop_variants: bool = False,
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
                if include_top_crop_variants:
                    for ratio, cropped_mask in _top_cropped_template_masks(mask, size):
                        packed, pixel_count = _pack_mask(cropped_mask)
                        templates.append(
                            DigitTemplate(
                                digit,
                                packed,
                                pixel_count,
                                (
                                    f"{source_prefix}:{Path(font_path).name}:"
                                    f"{font_size}:top-crop-{ratio:.2f}"
                                ),
                            )
                        )
    if templates:
        return templates

    raise RuntimeError(f"no OCR digit fonts found in {OCR_FONT_DIR}")


def _packed_jaccard(mask: int, pixel_count: int, template: DigitTemplate) -> float:
    intersection = (mask & template.mask).bit_count()
    union = pixel_count + template.pixel_count - intersection
    return float(intersection / union) if union else 0.0


def _score_mask_looks_like_one(mask) -> bool:
    height, width = mask.shape
    left_third = mask[:, : max(1, width // 3)]
    lower_left = left_third[height // 2 :, :]
    right_third = mask[:, width - max(1, width // 3) :]
    return bool(lower_left.mean() < 0.05 and right_third.mean() > 0.55)


def _score_digit_entry_looks_like_one(entry: ScoreDigitMask) -> bool:
    return bool(
        entry.width <= int(entry.image_width * 0.42)
        and _score_mask_looks_like_one(entry.mask)
    )


def _score_mask_looks_like_three(mask) -> bool:
    height, width = mask.shape
    left_third = mask[:, : max(1, width // 3)]
    middle_left = left_third[height // 3 : (height * 2) // 3, :]
    lower_left = left_third[height // 2 :, :]
    right_third = mask[:, width - max(1, width // 3) :]
    return bool(
        middle_left.mean() < 0.08
        and lower_left.mean() > 0.30
        and right_third.mean() > SCORE_THREE_MIN_RIGHT_DENSITY
    )


class FixedDigitClassifier:
    def __init__(
        self,
        size: tuple[int, int],
        font_sizes: range,
        source_prefix: str,
        templates: list[DigitTemplate] | None = None,
        include_top_crop_variants: bool = False,
    ):
        self.size = size
        self.templates = templates or _generated_templates(
            size,
            font_sizes,
            source_prefix,
            include_top_crop_variants=include_top_crop_variants,
        )

    def predict(
        self, mask, allowed_digits: frozenset[int] | None = None
    ) -> DigitPrediction:
        packed, pixel_count = _pack_mask(mask)
        best_digit = None
        best_similarity = 0.0
        best_source = "none"
        for template in self.templates:
            if allowed_digits is not None and template.digit not in allowed_digits:
                continue
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

        layout_readings = [
            (layout, self._read_layout(image, layout))
            for layout in _score_layouts(image.size)
        ]
        if image.size[0] < 240:
            for layout, reading in layout_readings:
                if (
                    layout.name == "compact_rendered"
                    and reading.has_layout
                    and reading.digits
                ):
                    return reading

        readings = [reading for _, reading in layout_readings]
        readings_with_digits = [
            reading for reading in readings if reading.has_layout and reading.digits
        ]
        if readings_with_digits:
            return max(readings_with_digits, key=self._reading_confidence)

        detected_boxes = _detected_rendered_score_cell_boxes(image)
        if detected_boxes:
            detected_reading = self._read_layout(
                image,
                ScoreLayout(
                    "detected_rendered",
                    detected_boxes,
                    ("green", "yellow", "red", "green", "yellow", "red"),
                ),
            )
            if detected_reading.has_layout and detected_reading.digits:
                return detected_reading

        readings_with_layout = [reading for reading in readings if reading.has_layout]
        if readings_with_layout:
            return max(readings_with_layout, key=self._reading_confidence)

        return readings[0]

    def _read_layout(self, image, layout: ScoreLayout) -> ScoreboardDigitReading:
        predictions = []
        has_layout = True
        for box, role in zip(layout.cell_boxes, layout.background_roles):
            raw_cell = image.crop(box)
            cell = _inner_cell(raw_cell)
            if not _score_cell_has_background(cell, role):
                has_layout = False
            prediction = self._predict_score_cell(cell)
            raw_prediction = self._predict_score_cell(raw_cell)
            if self._should_use_raw_score_prediction(prediction, raw_prediction):
                prediction = raw_prediction
            if prediction.digit is None:
                predictions.append(DigitPrediction(None, 0.0, "none"))
            else:
                predictions.append(prediction)
        if not has_layout or any(
            prediction.digit is None for prediction in predictions
        ):
            return ScoreboardDigitReading(None, tuple(predictions), has_layout)
        return ScoreboardDigitReading(
            tuple(prediction.digit for prediction in predictions),
            tuple(predictions),
            True,
        )

    def _predict_score_cell(self, cell) -> DigitPrediction:
        mask_entries = _score_digit_mask_entries(cell)
        if not mask_entries:
            return DigitPrediction(None, 0.0, "none")
        digit_predictions = [
            self._predict_score_digit_entry(entry, len(mask_entries))
            for entry in mask_entries[:2]
        ]
        if any(prediction.digit is None for prediction in digit_predictions):
            return DigitPrediction(None, 0.0, "none")
        value = int("".join(str(prediction.digit) for prediction in digit_predictions))
        similarity = sum(
            prediction.similarity for prediction in digit_predictions
        ) / len(digit_predictions)
        source = "+".join(prediction.source for prediction in digit_predictions)
        return DigitPrediction(value, similarity, source)

    @staticmethod
    def _prediction_digit_count(prediction: DigitPrediction) -> int:
        if prediction.digit is None:
            return 0
        return len(str(prediction.digit))

    @staticmethod
    def _prediction_has_leading_one_geometry(prediction: DigitPrediction) -> bool:
        return bool(
            prediction.digit is not None
            and str(prediction.digit).startswith("1")
            and (
                ":score-one-geometry" in prediction.source
                or ":score-leading-one-edge" in prediction.source
            )
        )

    @classmethod
    def _should_use_raw_score_prediction(
        cls, prediction: DigitPrediction, raw_prediction: DigitPrediction
    ) -> bool:
        if raw_prediction.digit is None:
            return False
        if prediction.digit is None:
            return True
        if not cls._prediction_has_leading_one_geometry(raw_prediction):
            return False
        if cls._prediction_has_leading_one_geometry(prediction):
            return False
        return cls._prediction_digit_count(
            raw_prediction
        ) >= cls._prediction_digit_count(prediction)

    def _predict_score_digit_entry(
        self, entry: ScoreDigitMask, mask_count: int
    ) -> DigitPrediction:
        if _score_digit_entry_looks_like_one(entry):
            one_prediction = self.classifier.predict(
                entry.mask, allowed_digits=frozenset((1,))
            )
            return DigitPrediction(
                1,
                one_prediction.similarity,
                f"{one_prediction.source}:score-one-geometry",
            )

        prediction = self._predict_score_digit(entry.mask)
        if (
            mask_count > 1
            and entry.x == 0
            and entry.width <= int(entry.image_width * 0.18)
        ):
            return DigitPrediction(
                1,
                prediction.similarity,
                f"{prediction.source}:score-leading-one-edge",
            )
        return prediction

    def _predict_score_digit(self, mask) -> DigitPrediction:
        prediction = self.classifier.predict(mask)
        if prediction.digit == 8 and _score_mask_looks_like_three(mask):
            three_prediction = self.classifier.predict(
                mask, allowed_digits=frozenset((3,))
            )
            if (
                three_prediction.digit == 3
                and three_prediction.similarity
                >= prediction.similarity - SCORE_THREE_EIGHT_SIMILARITY_MARGIN
            ):
                return DigitPrediction(
                    3,
                    three_prediction.similarity,
                    f"{three_prediction.source}:score-three-shape",
                )
        return prediction

    @staticmethod
    def _reading_confidence(reading: ScoreboardDigitReading) -> float:
        if not reading.predictions:
            return 0.0
        return float(
            sum(prediction.similarity for prediction in reading.predictions)
            / len(reading.predictions)
        )


class TimerDigitReader:
    MINUTE_TENS_DIGITS = frozenset((0, 1))
    SECOND_TENS_DIGITS = frozenset(range(6))
    MIN_DIGIT_COMPONENT_DENSITY = 0.30

    def __init__(self, classifier: FixedDigitClassifier | None = None):
        self.classifier = classifier or FixedDigitClassifier(
            TIMER_TEMPLATE_SIZE,
            range(44, 73, 4),
            "timer-font",
            include_top_crop_variants=True,
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
        if green_foreground > 0.03 and dark_background > 0.30:
            return "running"
        # Some tight crops include white scoreboard labels beside a green
        # timer. Prefer the timer's active digit color over that unrelated
        # white text when both appear on a dark-blue background.
        if green_foreground > 0.03 and dark_blue_background > 0.15:
            return "running"
        if white_foreground > 0.03 and dark_blue_background > 0.15:
            return "stopped"
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

    def _predict_digit(
        self, mask, allowed_digits: frozenset[int] | None = None
    ) -> DigitPrediction:
        prediction = self.classifier.predict(mask, allowed_digits=allowed_digits)
        if (
            prediction.digit == 0
            and (allowed_digits is None or 6 in allowed_digits)
            and self._looks_like_timer_six(mask)
        ):
            return DigitPrediction(
                6,
                prediction.similarity,
                f"{prediction.source}:timer-six-shape",
            )
        return prediction

    @classmethod
    def _allowed_digits_for_timer_masks(
        cls, mask_count: int
    ) -> list[frozenset[int] | None]:
        allowed_digits = [None] * mask_count
        if mask_count == 3:
            allowed_digits[1] = cls.SECOND_TENS_DIGITS
        elif mask_count == 4:
            allowed_digits[0] = cls.MINUTE_TENS_DIGITS
            allowed_digits[2] = cls.SECOND_TENS_DIGITS
        return allowed_digits

    def read(self, image) -> TimerDigitReading:
        state = self._state(image)
        if image is None or state in (None, "blank"):
            return TimerDigitReading(state, None, ())

        full_threshold = self._threshold(image, state)
        width, height = image.size
        display_left = int(width * 0.10)
        display_right = int(width * 0.88)
        # Exact timer crops have much less padding than the larger scoreboard
        # crops. Keep enough of their lower strokes for component detection.
        display_bottom_ratio = 0.90 if height < 40 else 0.80
        display_bottom = int(height * display_bottom_ratio)
        min_component_height = min(20, int(height * 0.65))
        display_mask = full_threshold[:display_bottom, display_left:display_right]
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
            display_mask.astype("uint8"), 8
        )

        components = []
        for component_index in range(1, component_count):
            x, y, component_width, component_height, area = stats[component_index]
            if (
                area < 40
                or component_height < min_component_height
                or component_width < 8
            ):
                continue
            if x == 0:
                continue
            if (
                area / (component_width * component_height)
                < self.MIN_DIGIT_COMPONENT_DENSITY
            ):
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

        masks = []
        for x, y, component_width, component_height, component_index in components:
            component_mask = (
                labels[
                    y : y + component_height,
                    x - display_left : x - display_left + component_width,
                ]
                == component_index
            )
            masks.append(_normalize_mask(component_mask, TIMER_TEMPLATE_SIZE))

        allowed_digits = self._allowed_digits_for_timer_masks(len(masks))

        predictions = [
            self._predict_digit(mask, allowed)
            for mask, allowed in zip(masks, allowed_digits)
        ]

        digits = [prediction.digit for prediction in predictions]
        if len(digits) == 3 and all(digit is not None for digit in digits):
            value = f"{digits[0]}:{digits[1]}{digits[2]}"
        elif len(digits) == 4 and all(digit is not None for digit in digits):
            minutes = digits[0] * 10 + digits[1]
            value = f"{minutes}:{digits[2]}{digits[3]}"
        else:
            return TimerDigitReading("blank", None, tuple(predictions))
        if value == "0:00":
            state = "stopped"
        return TimerDigitReading(state, value, tuple(predictions))


class FrameImageTextParser:
    def __init__(self, parser_profile: str, score_engine: str, name_engine: str | None):
        self.parser_profile = parser_profile
        self.score_engine = score_engine
        self.name_engine = name_engine
        self._score_timer_cache = {}
        self._name_cache = {}
        self._paddle_ocr = None
        self._paddle_result_cache = None
        score_enabled = score_engine not in (None, "none")
        self.score_reader = ScoreboardDigitReader() if score_enabled else None
        self.timer_reader = TimerDigitReader() if score_enabled else None
        if name_engine == "tesseract":
            import pytesseract  # noqa: F401
        elif name_engine == "paddle":
            _configure_paddle_runtime()
            import paddleocr  # noqa: F401

    @staticmethod
    def _image_cache_key(image_bytes):
        if image_bytes is None:
            return None
        if isinstance(image_bytes, bytes):
            return hashlib.blake2b(image_bytes, digest_size=16).digest()
        return repr(image_bytes)

    def _cache_attr(self, name: str):
        cache = getattr(self, name, None)
        if cache is None:
            cache = {}
            setattr(self, name, cache)
        return cache

    def _image_from_bytes(self, image_bytes):
        if not image_bytes:
            return None
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")

    def _ocr(self, image, config: str = "") -> str:
        if image is None:
            return ""
        if self.name_engine == "paddle":
            return self._paddle_image_to_string(image)
        import pytesseract

        return pytesseract.image_to_string(image, config=config).strip()

    def _paddle_reader(self):
        reader = getattr(self, "_paddle_ocr", None)
        if reader is not None:
            return reader

        _configure_paddle_runtime()
        from paddleocr import PaddleOCR

        init_kwargs_options = (
            {
                "lang": "en",
                "ocr_version": "PP-OCRv5",
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "enable_mkldnn": False,
                "cpu_threads": 1,
                "device": "cpu",
            },
            {
                "lang": "en",
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "enable_mkldnn": False,
                "cpu_threads": 1,
                "device": "cpu",
            },
            {
                "use_angle_cls": True,
                "lang": "en",
                "enable_mkldnn": False,
                "cpu_threads": 1,
            },
            {"lang": "en"},
        )
        for kwargs in init_kwargs_options:
            try:
                reader = PaddleOCR(**kwargs)
                break
            except (TypeError, ValueError):
                reader = None
        if reader is None:
            reader = PaddleOCR()
        self._paddle_ocr = reader
        return reader

    def _paddle_ocr_result(self, image):
        if image is None:
            return None
        if Image is not None and hasattr(image, "convert"):
            image = image.convert("RGB")
        result_cache = getattr(self, "_paddle_result_cache", None)
        cache_key = None
        if result_cache is not None and hasattr(image, "tobytes"):
            cache_key = (
                image.size,
                hashlib.blake2b(image.tobytes(), digest_size=16).digest(),
            )
            if cache_key in result_cache:
                return result_cache[cache_key]
        ocr_input = (
            np.asarray(image) if np is not None and hasattr(image, "size") else image
        )
        reader = self._paddle_reader()
        try:
            result = reader.ocr(ocr_input, cls=True)
        except (TypeError, ValueError):
            result = reader.ocr(ocr_input)
        if cache_key is not None:
            result_cache[cache_key] = result
        return result

    def _paddle_image_to_string(self, image) -> str:
        result = self._paddle_ocr_result(image)
        return "\n".join(
            text
            for text, _confidence in self._paddle_text_items(result)
            if text.strip()
        ).strip()

    def _paddle_name_texts(self, score_image, column_boxes):
        if score_image is None or not hasattr(score_image, "crop"):
            yield self._ocr(score_image)
            return

        boxes = [column_boxes[0]]
        for box in column_boxes[1:]:
            if box not in boxes:
                boxes.append(box)

        crops = [score_image.crop(box) for box in boxes]
        for crop in crops:
            yield self._ocr(crop)

        for crop in crops:
            prepared = self._prepare_paddle_retry_image(crop)
            if prepared is not None:
                yield self._ocr(prepared)

    def _paddle_name_fields(self, score_image, column_boxes, *, compact_name_column):
        direct_text, direct_fields = self._paddle_direct_row_name_fields(score_image)
        if direct_fields:
            return direct_text, direct_fields

        box_text, box_fields = self._paddle_box_name_fields(
            score_image, column_boxes[0]
        )
        if box_fields:
            return box_text, box_fields

        first_text = ""
        compact_top_name = None
        for text in self._paddle_name_texts(score_image, column_boxes):
            if not first_text:
                first_text = text
            victory_fields = self._complete_athlete_name_fields(
                self._parse_victory_names(text)
            )
            if victory_fields:
                return text, victory_fields
            fields = self._complete_athlete_name_fields(
                self._parse_names(
                    text,
                    allow_two_line_fallback=compact_name_column,
                    reject_lowercase_artifacts=compact_name_column,
                )
            )
            if fields:
                return text, fields
            if compact_name_column:
                parsed_names = self._parse_names(text, allow_two_line_fallback=False)
                if parsed_names.get("top_athlete_name") and not parsed_names.get(
                    "bottom_athlete_name"
                ):
                    compact_top_name = parsed_names["top_athlete_name"]
        row_text, row_fields = self._paddle_row_name_fields(
            score_image, top_name_fallback=compact_top_name
        )
        if row_fields:
            return (
                "\n".join(part for part in (first_text, row_text) if part),
                row_fields,
            )
        return first_text, {}

    def _paddle_recognize_lines(self, images) -> list[str] | None:
        if np is None or not images:
            return None
        reader = self._paddle_reader()
        # PaddleOCR 3.7 keeps the loaded recognizer on its pipeline. Using it here
        # avoids rerunning text detection for crops that already contain one row.
        # Keep this optional so a future PaddleOCR layout falls back to full OCR.
        pipeline = getattr(reader, "paddlex_pipeline", None)
        recognizer = getattr(pipeline, "text_rec_model", None)
        if recognizer is None:
            return None

        recognition_inputs = []
        for image in images:
            if image is None or not hasattr(image, "convert"):
                return None
            rgb = np.asarray(image.convert("RGB"))
            recognition_inputs.append(rgb[:, :, ::-1].copy())
        try:
            results = list(recognizer(recognition_inputs))
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        if len(results) != len(images):
            return None

        texts = []
        for result in results:
            if hasattr(result, "get"):
                text = result.get("rec_text", "")
            else:
                text = getattr(result, "rec_text", "")
            texts.append(str(text or "").strip())
        return texts

    def _paddle_direct_row_name_fields(self, score_image) -> tuple[str, dict]:
        if score_image is None or not hasattr(score_image, "crop"):
            return "", {}
        width, height = score_image.size
        if not (
            PADDLE_DIRECT_ROW_MIN_WIDTH <= width < 240
            and height <= PADDLE_DIRECT_ROW_MAX_HEIGHT
        ):
            return "", {}

        base_boxes = _name_line_boxes(score_image.size)
        top_crop = score_image.crop(base_boxes[0])
        bottom_crop = score_image.crop(base_boxes[1])
        alternate_bottom_crop = score_image.crop(
            (
                0,
                int(height * 0.40),
                int(width * 0.55),
                int(height * 0.65),
            )
        )
        image_groups = (
            (
                "top_athlete_name",
                [
                    top_crop,
                    self._prepare_paddle_retry_image(top_crop),
                    self._prepare_paddle_scaled_retry_image(top_crop),
                ],
            ),
            (
                "bottom_athlete_name",
                [
                    bottom_crop,
                    self._prepare_paddle_retry_image(bottom_crop),
                    self._prepare_paddle_scaled_retry_image(alternate_bottom_crop),
                    self._prepare_paddle_scaled_retry_image(bottom_crop),
                ],
            ),
        )
        images = [image for _field_name, group in image_groups for image in group]
        texts = self._paddle_recognize_lines(images)
        if texts is None:
            return "", {}

        fields = {}
        offset = 0
        for field_name, group in image_groups:
            candidates = []
            for text in texts[offset : offset + len(group)]:
                candidate = self._name_from_row_text(text)
                if not candidate and field_name == "bottom_athlete_name":
                    candidate = self._name_from_paddle_item_text(
                        " ".join(text.splitlines())
                    )
                if candidate:
                    candidates.append(candidate)
            offset += len(group)
            if candidates:
                fields[field_name] = max(candidates, key=self._name_candidate_score)

        return "\n".join(
            text for text in texts if text
        ), self._complete_athlete_name_fields(fields)

    def _paddle_row_name_fields(
        self, score_image, *, top_name_fallback: str | None = None
    ) -> tuple[str, dict]:
        if score_image is None or not hasattr(score_image, "crop"):
            return "", {}

        row_fields = {}
        row_texts = []
        use_scaled_retry = score_image.size[0] < 240
        base_boxes = _name_line_boxes(score_image.size)
        row_box_groups = [
            ("top_athlete_name", [base_boxes[0]]),
            ("bottom_athlete_name", [base_boxes[1]]),
        ]
        if use_scaled_retry:
            width, height = score_image.size
            row_box_groups[1][1].append(
                (
                    0,
                    int(height * 0.40),
                    int(width * 0.55),
                    int(height * 0.65),
                )
            )

        for field_name, boxes in row_box_groups:
            name_candidates = []
            crop = score_image.crop(boxes[0])
            base_images = [crop, self._prepare_paddle_retry_image(crop)]

            def read_candidate(image):
                if image is None:
                    return None
                text = self._ocr(image)
                if text:
                    row_texts.append(text)
                name_candidate = self._name_from_row_text(text)
                if (
                    not name_candidate
                    and use_scaled_retry
                    and field_name == "bottom_athlete_name"
                ):
                    name_candidate = self._name_from_paddle_item_text(
                        " ".join(text.splitlines())
                    )
                return name_candidate

            for image in base_images:
                name_candidate = read_candidate(image)
                if name_candidate:
                    name_candidates.append(name_candidate)
                    if not use_scaled_retry and not self._needs_name_retry(
                        name_candidate
                    ):
                        break

            if use_scaled_retry and not self._name_candidates_agree(name_candidates):
                scaled_retry_images = [
                    self._prepare_paddle_scaled_retry_image(score_image.crop(box))
                    for box in boxes[1:]
                ]
                scaled_retry_images.append(
                    self._prepare_paddle_scaled_retry_image(crop)
                )
                for image in scaled_retry_images:
                    name_candidate = read_candidate(image)
                    if name_candidate:
                        name_candidates.append(name_candidate)
            if name_candidates:
                row_fields[field_name] = max(
                    name_candidates, key=self._name_candidate_score
                )
        if top_name_fallback and not row_fields.get("top_athlete_name"):
            row_fields["top_athlete_name"] = top_name_fallback

        return "\n".join(row_texts), self._complete_athlete_name_fields(row_fields)

    def _paddle_box_name_fields(self, score_image, column_box) -> tuple[str, dict]:
        if score_image is None or not hasattr(score_image, "crop"):
            return "", {}

        crop = score_image.crop(column_box)
        result = self._paddle_ocr_result(crop)
        items = [
            item
            for item in self._paddle_text_items_with_boxes(result)
            if item.text.strip() and item.box is not None
        ]
        if not items:
            return "", {}

        items.sort(key=lambda item: (item.box[1], item.box[0]))
        text = "\n".join(item.text for item in items)
        row_items = {
            "top_athlete_name": [],
            "bottom_athlete_name": [],
        }
        row_boundary = score_image.size[1] * NAME_ROW_Y_EDGES[1]
        column_top = column_box[1]
        for item in items:
            y_center = column_top + (item.box[1] + item.box[3]) / 2
            if y_center < row_boundary:
                row_items["top_athlete_name"].append(item)
            else:
                row_items["bottom_athlete_name"].append(item)

        fields = {}
        for field_name, candidates in row_items.items():
            name = self._best_paddle_row_name(candidates)
            if name:
                fields[field_name] = name
        return text, self._complete_athlete_name_fields(fields)

    def _best_paddle_row_name(self, items: list[PaddleTextItem]) -> str | None:
        candidates = []
        for item in self._paddle_row_line_items(items):
            name = self._name_from_paddle_item_text(item.text)
            if not name:
                continue
            candidates.append((name, self._looks_like_team_line(name)))
        if not candidates:
            return None
        for name, is_team_line in candidates:
            if not is_team_line:
                return name
        return candidates[0][0]

    def _paddle_row_line_items(
        self, items: list[PaddleTextItem]
    ) -> list[PaddleTextItem]:
        line_groups = []
        for item in sorted(items, key=lambda item: (item.box[1], item.box[0])):
            y_center = (item.box[1] + item.box[3]) / 2
            height = max(1.0, item.box[3] - item.box[1])
            for group in line_groups:
                threshold = max(6.0, group["height"], height) * 0.75
                if abs(y_center - group["y_center"]) <= threshold:
                    group["items"].append(item)
                    group["y_center"] = sum(
                        (group_item.box[1] + group_item.box[3]) / 2
                        for group_item in group["items"]
                    ) / len(group["items"])
                    group["height"] = max(group["height"], height)
                    break
            else:
                line_groups.append(
                    {
                        "items": [item],
                        "y_center": y_center,
                        "height": height,
                    }
                )

        line_items = []
        for group in line_groups:
            group_items = sorted(group["items"], key=lambda item: item.box[0])
            text = " ".join(
                item.text.strip() for item in group_items if item.text.strip()
            )
            if not text:
                continue
            xs = [
                coordinate
                for item in group_items
                for coordinate in (item.box[0], item.box[2])
            ]
            ys = [
                coordinate
                for item in group_items
                for coordinate in (item.box[1], item.box[3])
            ]
            scores = [
                item.confidence
                for item in group_items
                if isinstance(item.confidence, (int, float))
            ]
            confidence = sum(scores) / len(scores) if scores else None
            line_items.append(
                PaddleTextItem(
                    text,
                    confidence,
                    (min(xs), min(ys), max(xs), max(ys)),
                )
            )
        return sorted(line_items, key=lambda item: (item.box[1], item.box[0]))

    def _name_from_paddle_item_text(self, text: str) -> str | None:
        line = self._clean_text_line(text)
        if line is None:
            return None
        tokens = line.split()
        if len(tokens) >= 3:
            last_letters = re.sub(r"[^\w]|[\d_]", "", tokens[-1])
            if len(last_letters) == 1 and re.search(r"\.{2,}\s*$", text):
                line = " ".join(tokens[:-1])
                tokens = line.split()
        substantial_tokens = [
            token for token in tokens if len(re.sub(r"[^\w]|[\d_]", "", token)) >= 2
        ]
        if len(substantial_tokens) < 2:
            return None
        if self._looks_like_junk_name_line(line):
            return None
        return line

    def _prepare_paddle_retry_image(self, image):
        if image is None or ImageOps is None:
            return None
        return ImageOps.autocontrast(ImageOps.grayscale(image)).convert("RGB")

    def _prepare_paddle_scaled_retry_image(self, image):
        if image is None or ImageOps is None:
            return None
        prepared = ImageOps.autocontrast(ImageOps.grayscale(image))
        return prepared.resize(
            (
                prepared.width * PADDLE_ROW_NAME_RETRY_SCALE,
                prepared.height * PADDLE_ROW_NAME_RETRY_SCALE,
            ),
            Image.Resampling.LANCZOS,
        ).convert("RGB")

    @classmethod
    def _paddle_text_items(cls, result):
        return [
            (item.text, item.confidence)
            for item in cls._paddle_text_items_with_boxes(result)
        ]

    @classmethod
    def _paddle_text_items_with_boxes(cls, result):
        if result is None:
            return []
        if isinstance(result, dict):
            if "rec_texts" in result:
                texts = result.get("rec_texts") or []
                scores = result.get("rec_scores") or []
                boxes = cls._paddle_result_boxes(result)
                return [
                    PaddleTextItem(
                        str(text),
                        scores[index] if index < len(scores) else None,
                        (
                            cls._paddle_box_bounds(boxes[index])
                            if index < len(boxes)
                            else None
                        ),
                    )
                    for index, text in enumerate(texts)
                    if text
                ]
            if isinstance(result.get("text"), str):
                return [
                    PaddleTextItem(
                        result["text"],
                        result.get("score", result.get("confidence")),
                        cls._paddle_box_bounds(cls._paddle_result_box(result)),
                    )
                ]
            items = []
            for value in result.values():
                items.extend(cls._paddle_text_items_with_boxes(value))
            return items
        if isinstance(result, (list, tuple)):
            if (
                len(result) >= 2
                and isinstance(result[0], str)
                and isinstance(result[1], (int, float))
            ):
                return [PaddleTextItem(result[0], result[1])]
            if (
                len(result) >= 2
                and isinstance(result[1], (list, tuple))
                and len(result[1]) >= 2
                and isinstance(result[1][0], str)
            ):
                return [
                    PaddleTextItem(
                        result[1][0],
                        result[1][1],
                        cls._paddle_box_bounds(result[0]),
                    )
                ]
            items = []
            for value in result:
                items.extend(cls._paddle_text_items_with_boxes(value))
            return items
        return []

    @staticmethod
    def _paddle_result_boxes(result: dict):
        for key in ("rec_boxes", "rec_polys", "dt_polys"):
            if key in result and result[key] is not None:
                return result[key]
        return []

    @staticmethod
    def _paddle_result_box(result: dict):
        for key in ("box", "bbox", "points"):
            if key in result and result[key] is not None:
                return result[key]
        return None

    @classmethod
    def _paddle_box_bounds(cls, box):
        if box is None:
            return None
        if np is not None and isinstance(box, np.ndarray):
            box = box.tolist()
        if isinstance(box, (list, tuple)):
            if len(box) == 4 and all(isinstance(value, (int, float)) for value in box):
                x1, y1, x2, y2 = box
                return (float(x1), float(y1), float(x2), float(y2))
            points = cls._paddle_box_points(box)
            if points:
                xs = [point[0] for point in points]
                ys = [point[1] for point in points]
                return (min(xs), min(ys), max(xs), max(ys))
        return None

    @classmethod
    def _paddle_box_points(cls, value):
        if np is not None and isinstance(value, np.ndarray):
            value = value.tolist()
        if not isinstance(value, (list, tuple)):
            return []
        if len(value) >= 2 and all(
            isinstance(component, (int, float)) for component in value[:2]
        ):
            return [(float(value[0]), float(value[1]))]
        points = []
        for item in value:
            points.extend(cls._paddle_box_points(item))
        return points

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

    def _name_from_row_text(
        self, text: str, *, reject_lowercase_artifacts: bool = False
    ) -> str | None:
        for raw_line in text.splitlines():
            cleaned_line = self._clean_name_line(
                raw_line,
                reject_lowercase_artifacts=reject_lowercase_artifacts,
            )
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
        compact_name_column = score_image.size[0] < 240 and len(column_boxes) > 1
        if self.name_engine == "paddle":
            previous_result_cache = getattr(self, "_paddle_result_cache", None)
            self._paddle_result_cache = {}
            try:
                return self._paddle_name_fields(
                    score_image,
                    column_boxes,
                    compact_name_column=compact_name_column,
                )
            finally:
                self._paddle_result_cache = previous_result_cache

        compact_top_name = None
        for index, box in enumerate(column_boxes):
            column_image = self._prepare_name_ocr_image(score_image.crop(box))
            column_text = self._ocr(column_image, "--psm 6")
            victory_fields = self._complete_athlete_name_fields(
                self._parse_victory_names(column_text)
            )
            if victory_fields:
                return column_text, victory_fields

            parsed_names = self._parse_names(
                column_text,
                allow_two_line_fallback=compact_name_column,
                reject_lowercase_artifacts=compact_name_column,
            )
            if (
                compact_name_column
                and parsed_names.get("top_athlete_name")
                and parsed_names.get("top_athlete_name")
                == parsed_names.get("bottom_athlete_name")
            ):
                parsed_names.pop("bottom_athlete_name", None)
            if (
                compact_name_column
                and parsed_names.get("top_athlete_name")
                and not parsed_names.get("bottom_athlete_name")
            ):
                if compact_top_name is None or self._name_candidate_score(
                    parsed_names["top_athlete_name"]
                ) > self._name_candidate_score(compact_top_name):
                    compact_top_name = parsed_names["top_athlete_name"]

            parsed_column_fields = self._complete_athlete_name_fields(parsed_names)
            if (
                parsed_column_fields
                and compact_top_name
                and self._name_candidate_score(compact_top_name)
                > self._name_candidate_score(parsed_column_fields["top_athlete_name"])
            ):
                parsed_column_fields = {
                    **parsed_column_fields,
                    "top_athlete_name": compact_top_name,
                }
            if parsed_column_fields and len(column_boxes) > 1 and index == 0:
                return column_text, parsed_column_fields
            if parsed_column_fields:
                column_fields = parsed_column_fields

        if compact_name_column:
            if column_fields:
                return column_text, column_fields
            compact_row_fields = self._compact_row_name_fields(
                score_image, top_name_fallback=compact_top_name
            )
            if compact_row_fields:
                return column_text, compact_row_fields

        if column_fields and len(column_boxes) > 1:
            return column_text, column_fields

        row_fields = {}
        row_texts = []
        for field_name, box in zip(
            ("top_athlete_name", "bottom_athlete_name"),
            _name_line_boxes(score_image.size),
        ):
            name_image = self._prepare_name_ocr_image(score_image.crop(box))
            row_text_parts = []
            name_candidates = []
            for config in ("--psm 7", "--psm 6"):
                text = self._ocr(name_image, config)
                if text:
                    row_text_parts.append(text)
                name_candidate = self._name_from_row_text(text)
                if name_candidate:
                    name_candidates.append(name_candidate)
                    if not self._needs_name_retry(name_candidate):
                        break
            if name_candidates and self._needs_name_retry(name_candidates[-1]):
                text = self._ocr(name_image, "--psm 11")
                if text:
                    row_text_parts.append(text)
                name_candidate = self._name_from_row_text(text)
                if name_candidate:
                    name_candidates.append(name_candidate)
            row_text = "\n".join(row_text_parts)
            name = None
            if name_candidates:
                name = max(name_candidates, key=self._name_candidate_score)
            if row_text:
                row_texts.append(row_text)
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
            token = token.strip("\"'‘’“”`´,:;()[]{}<>")
            if re.search(r"\d", token):
                break
            if not re.match(r"^[^\W\d_](?:[^\W\d_]|['.,:-])*$", token):
                continue
            tokens.append(token)
        line = " ".join(tokens)
        line = re.sub(r"\s+", " ", line).strip(" -:")
        line = line.strip(" -:.,'")
        alpha_tokens = line.split()
        if len(alpha_tokens) >= 4:
            first_two_letters = [
                re.sub(r"[^A-Za-z]", "", token) for token in alpha_tokens[:2]
            ]
            rest_lengths = [
                len(re.sub(r"[^A-Za-z]", "", token)) for token in alpha_tokens[2:]
            ]
            if (
                all(
                    len(letters) >= 2 and letters == letters.upper()
                    for letters in first_two_letters
                )
                and rest_lengths
                and all(length <= 2 for length in rest_lengths)
            ):
                line = " ".join(alpha_tokens[:2]).strip(" -:.,'")
                alpha_tokens = line.split()
        if not re.search(r"[^\W\d_]", line):
            return None
        if re.fullmatch(
            r"(?:P|PTS|POINTS|A|ADV|ADVANTAGES|PEN|PENALTIES|SCORE|TIME|TIMER)"
            r"(?:\s+|/|-|:)*",
            line,
            flags=re.IGNORECASE,
        ):
            return None
        if self._looks_like_junk_name_line(line):
            return None
        total_letters = sum(
            len(re.sub(r"[^\w]|[\d_]", "", token)) for token in alpha_tokens
        )
        if total_letters < 6:
            return None
        return line

    def _clean_name_line(
        self, line: str, *, reject_lowercase_artifacts: bool = False
    ) -> str | None:
        line = self._clean_text_line(line)
        if line is None:
            return None
        if reject_lowercase_artifacts and self._looks_like_lowercase_ocr_artifact(line):
            return None
        alpha_tokens = line.split()
        substantial_tokens = [
            token
            for token in alpha_tokens
            if len(re.sub(r"[^\w]|[\d_]", "", token)) >= 2
        ]
        if len(substantial_tokens) < 2:
            return None
        uppercase_prefix = self._uppercase_name_prefix(alpha_tokens)
        if len(uppercase_prefix) >= 2:
            line = " ".join(uppercase_prefix)
            line = re.sub(r"\.+$", "", line).strip(" -:.,'")
        if self._looks_like_junk_name_line(line):
            return None
        return line

    @staticmethod
    def _uppercase_name_prefix(tokens: list[str]) -> list[str]:
        prefix = []
        for token in tokens:
            letters = re.sub(r"[^\w]|[\d_]", "", token)
            if len(letters) < 2 or letters != letters.upper():
                break
            prefix.append(token)
        return prefix

    @classmethod
    def _needs_name_retry(cls, name: str) -> bool:
        tokens = name.split()
        if not tokens:
            return True
        letter_count = sum(len(re.sub(r"[^\w]|[\d_]", "", token)) for token in tokens)
        if letter_count < 10:
            return True
        first_letters = re.sub(r"[^\w]|[\d_]", "", tokens[0])
        if len(first_letters) < 2 or first_letters != first_letters.upper():
            return False
        return len(cls._uppercase_name_prefix(tokens)) < 2

    @classmethod
    def _name_candidates_agree(cls, candidates: list[str]) -> bool:
        return (
            len(candidates) >= 2
            and candidates[-1] == candidates[-2]
            and not cls._needs_name_retry(candidates[-1])
        )

    @classmethod
    def _name_candidate_score(cls, name: str) -> int:
        tokens = name.split()
        uppercase_prefix = cls._uppercase_name_prefix(tokens)
        if len(uppercase_prefix) >= 2:
            return 100 + sum(
                len(re.sub(r"[^\w]|[\d_]", "", token)) for token in uppercase_prefix
            )
        return sum(len(re.sub(r"[^\w]|[\d_]", "", token)) for token in tokens)

    @classmethod
    def _looks_like_junk_name_line(cls, name: str) -> bool:
        tokens = name.split()
        token_lengths = [sum(1 for char in token if char.isalpha()) for token in tokens]
        token_lengths = [length for length in token_lengths if length]
        if len(token_lengths) < 4:
            return False
        short_count = sum(length <= 3 for length in token_lengths)
        long_count = sum(length >= 5 for length in token_lengths)
        if short_count > len(token_lengths) // 2 and long_count <= 1:
            normalized_tokens = [
                "".join(
                    char
                    for char in unicodedata.normalize("NFKD", token)
                    if not unicodedata.combining(char)
                ).upper()
                for token in tokens
            ]
            name_particles = {
                "DA",
                "DAS",
                "DE",
                "DEL",
                "DI",
                "DO",
                "DOS",
                "DU",
                "E",
                "LA",
                "LE",
                "SA",
                "VAN",
                "VON",
            }
            substantial_name_tokens = [
                token
                for token in normalized_tokens
                if len(re.sub(r"[^A-Z]", "", token)) >= 4
            ]
            short_tokens = [
                token
                for token in normalized_tokens
                if 0 < len(re.sub(r"[^A-Z]", "", token)) <= 3
            ]
            if (
                len(substantial_name_tokens) >= 2
                and short_tokens
                and all(token in name_particles for token in short_tokens)
            ):
                return False
        return short_count > len(token_lengths) // 2 and long_count <= 1

    @staticmethod
    def _looks_like_lowercase_ocr_artifact(name: str) -> bool:
        letters = re.sub(r"[^A-Za-z]", "", name)
        if len(letters) < 6:
            return False
        lowercase_count = sum(letter.islower() for letter in letters)
        uppercase_count = sum(letter.isupper() for letter in letters)
        return lowercase_count >= 6 and lowercase_count >= max(1, uppercase_count * 3)

    def _compact_row_name_candidate(self, score_image, box) -> str | None:
        name_image = self._prepare_name_ocr_image(score_image.crop(box))
        for config in ("--psm 7", "--psm 6"):
            candidate = self._name_from_row_text(
                self._ocr(name_image, config),
                reject_lowercase_artifacts=True,
            )
            if candidate:
                return candidate
        return None

    def _first_compact_row_name(self, score_image, boxes) -> str | None:
        for box in boxes:
            candidate = self._compact_row_name_candidate(score_image, box)
            if candidate:
                return candidate
        return None

    def _compact_row_name_fields(
        self, score_image, *, top_name_fallback: str | None = None
    ) -> dict:
        if score_image is None or not hasattr(score_image, "crop"):
            return {}

        width, _ = score_image.size
        top_right_edges = (0.52, 0.535, NAME_COLUMN_RIGHT_RATIO)
        bottom_right_edges = (NAME_COLUMN_RIGHT_RATIO, 0.52, 0.535)
        top_boxes = [
            (0, 0, int(width * right_edge), 13) for right_edge in top_right_edges
        ]
        bottom_boxes = [
            (0, top, int(width * right_edge), bottom)
            for top, bottom in ((39, 55), (38, 54), (36, 52))
            for right_edge in bottom_right_edges
        ]
        top_name = self._first_compact_row_name(score_image, top_boxes)
        if not top_name:
            top_name = top_name_fallback
        bottom_name = self._first_compact_row_name(score_image, bottom_boxes)
        return self._complete_athlete_name_fields(
            {
                "top_athlete_name": top_name,
                "bottom_athlete_name": bottom_name,
            }
        )

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
        if len(lines) >= 5:
            if FrameImageTextParser._looks_like_team_line(
                lines[2]
            ) and FrameImageTextParser._looks_like_team_line(lines[4]):
                return {
                    "top_athlete_name": f"{lines[0]} {lines[1]}",
                    "bottom_athlete_name": lines[3],
                }
            if FrameImageTextParser._looks_like_team_line(
                lines[1]
            ) and FrameImageTextParser._looks_like_team_line(lines[4]):
                return {
                    "top_athlete_name": lines[0],
                    "bottom_athlete_name": f"{lines[2]} {lines[3]}",
                }
        return {
            "top_athlete_name": lines[0],
            "bottom_athlete_name": lines[2],
        }

    @staticmethod
    def _looks_like_team_line(line: str) -> bool:
        normalized = unicodedata.normalize("NFKD", line)
        normalized = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
        team_terms = (
            "academy",
            "alliance",
            "barra",
            "bjj",
            "champ",
            "checkmat",
            "college",
            "fight sports",
            "gracie",
            "jiu jitsu",
            "nexo",
            "nova uniao",
            "pro training",
            "team",
        )
        return any(term in normalized for term in team_terms)

    def _parse_names(
        self,
        text: str,
        *,
        allow_two_line_fallback: bool = True,
        reject_lowercase_artifacts: bool = False,
    ) -> dict:
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
            if (
                cleaned_line
                and reject_lowercase_artifacts
                and self._looks_like_lowercase_ocr_artifact(cleaned_line)
            ):
                cleaned_line = None
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

    def _score_timer_readings(self, score_image, timer_image, score, timer):
        score_enabled = self.score_engine not in (None, "none")
        cache = self._cache_attr("_score_timer_cache")
        cache_key = (
            self.score_engine,
            self._image_cache_key(score_image),
            self._image_cache_key(timer_image),
        )
        if cache_key in cache:
            return cache[cache_key]

        score_reading = self.score_reader.read(score) if self.score_reader else None
        timer_reading = self.timer_reader.read(timer) if self.timer_reader else None
        score_fields = score_fields_from_reading(score_reading) if score_enabled else {}
        timer_state = timer_reading.state if timer_reading else None
        timer_value = timer_reading.value if timer_reading else None
        result = (
            score_reading,
            timer_reading,
            score_fields,
            timer_state,
            timer_value,
        )
        cache[cache_key] = result
        return result

    @classmethod
    def _name_region_cache_key(cls, score_image, score):
        if score is None or not hasattr(score, "crop") or not hasattr(score, "size"):
            return cls._image_cache_key(score_image)

        boxes = [*_name_column_boxes(score.size), *_name_line_boxes(score.size)]
        if score.size[0] < 240:
            width, height = score.size
            boxes.append(
                (
                    0,
                    int(height * 0.40),
                    int(width * 0.55),
                    int(height * 0.65),
                )
            )
        right = max(box[2] for box in boxes)
        bottom = max(box[3] for box in boxes)
        name_region = score.crop((0, 0, right, bottom)).convert("RGB")
        return (
            score.size,
            (right, bottom),
            hashlib.blake2b(name_region.tobytes(), digest_size=16).digest(),
        )

    def _cached_name_fields(self, score_image, score):
        name_enabled = self.name_engine not in (None, "none")
        if not name_enabled:
            return "", {}

        cache = self._cache_attr("_name_cache")
        cache_key = (self.name_engine, self._name_region_cache_key(score_image, score))
        if cache_key not in cache:
            cache[cache_key] = self._ocr_name_fields(score)
        return cache[cache_key]

    def parse_score_timer(
        self, frame_second: int, score_image, timer_image
    ) -> FrameReading:
        return self._parse(frame_second, score_image, timer_image, include_names=False)

    def parse(self, frame_second: int, score_image, timer_image) -> FrameReading:
        return self._parse(frame_second, score_image, timer_image, include_names=True)

    def _parse(
        self,
        frame_second: int,
        score_image,
        timer_image,
        *,
        include_names: bool,
    ) -> FrameReading:
        score = self._image_from_bytes(score_image)
        timer = self._image_from_bytes(timer_image)
        if include_names:
            scoreboard_text, name_fields = self._cached_name_fields(score_image, score)
        else:
            scoreboard_text, name_fields = "", {}
        (
            score_reading,
            timer_reading,
            score_fields,
            timer_state,
            timer_value,
        ) = self._score_timer_readings(score_image, timer_image, score, timer)
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
    elif name_engine == "paddle":
        try:
            _configure_paddle_runtime()
            import paddleocr  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "paddle name engine requires paddleocr and paddlepaddle"
            ) from exc
        if Image is None or np is None:
            raise RuntimeError(
                "paddle name engine requires paddleocr, numpy, and pillow"
            )


def build_parser(parser_profile: str, score_engine: str, name_engine: str | None):
    if score_engine == "none" and name_engine in (None, "none"):
        return EmptyTextParser()
    return FrameImageTextParser(parser_profile, score_engine, name_engine)
