#!/usr/bin/env python3
"""Probe fixed-layout scoreboard digits from archived livestream frame crops.

This is intentionally standalone. It does not use the database, scanner event
logic, binary search, score plausibility rules, or Tesseract for score digits.
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS_CSV = REPO_ROOT / "scripts" / "probe_scoreboard_digit_labels.csv"
SCORE_FIELDS = (
    "top_points",
    "top_advantages",
    "top_penalties",
    "bottom_points",
    "bottom_advantages",
    "bottom_penalties",
)
SCORE_TEMPLATE_SIZE = (24, 36)
TIMER_TEMPLATE_SIZE = (28, 48)


@dataclass(frozen=True)
class Label:
    second: int
    score_digits: tuple[
        int | None, int | None, int | None, int | None, int | None, int | None
    ]
    timer_state: str | None
    timer_value: str | None


@dataclass(frozen=True)
class DigitPrediction:
    digit: int | None
    similarity: float
    source: str
    normalized_mask: np.ndarray | None
    threshold_mask: np.ndarray | None


@dataclass(frozen=True)
class DigitTemplate:
    digit: int
    mask: int
    pixel_count: int
    source: str


@dataclass(frozen=True)
class ScoreReading:
    digits: tuple[int, int, int, int, int, int] | None
    predictions: tuple[DigitPrediction, ...]
    cell_boxes: tuple[tuple[int, int, int, int], ...]
    has_layout: bool


@dataclass(frozen=True)
class TimerReading:
    state: str | None
    value: str | None
    predictions: tuple[DigitPrediction, ...]
    threshold_mask: np.ndarray | None


@dataclass(frozen=True)
class FrameReading:
    second: int
    score: ScoreReading
    timer: TimerReading


def load_labels(path: Path) -> list[Label]:
    labels = []
    with path.open(newline="") as file:
        for row in csv.DictReader(file):
            score_digits = tuple(
                int(row[field]) if row[field] != "" else None for field in SCORE_FIELDS
            )
            labels.append(
                Label(
                    second=int(row["second"]),
                    score_digits=score_digits,
                    timer_state=row["timer_state"] or None,
                    timer_value=row["timer_value"] or None,
                )
            )
    return labels


def score_cell_boxes(
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


def inner_cell(image: Image.Image) -> Image.Image:
    margin = max(2, min(image.size) // 12)
    return image.crop((margin, margin, image.width - margin, image.height - margin))


def score_cell_has_background(image: Image.Image, cell_index: int) -> bool:
    rgb = np.asarray(image.convert("RGB"))
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    if cell_index % 3 == 2:
        mask = (red > 120) & (green < 110) & (blue < 130)
    else:
        mask = (green > 100) & (blue < 150) & (red < 190)
    return bool(mask.mean() >= 0.12)


def score_digit_threshold(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"))
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    spread = np.maximum.reduce([red, green, blue]) - np.minimum.reduce(
        [red, green, blue]
    )
    return (red > 145) & (green > 145) & (blue > 95) & (spread < 120)


def largest_component(
    mask: np.ndarray, min_area: int
) -> tuple[np.ndarray, tuple[int, int, int, int]] | None:
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
    component = labels[y : y + height, x : x + width] == component_index
    return component, (int(x), int(y), int(width), int(height))


def normalize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    image = Image.fromarray(mask.astype("uint8") * 255, "L")
    return np.asarray(image.resize(size, Image.Resampling.NEAREST)) > 0


def score_digit_mask(image: Image.Image) -> tuple[np.ndarray, np.ndarray] | None:
    threshold = score_digit_threshold(image)
    component = largest_component(threshold, min_area=20)
    if component is None:
        return None
    component_mask, _ = component
    return normalize_mask(component_mask, SCORE_TEMPLATE_SIZE), threshold


def font_paths() -> tuple[str, ...]:
    return (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Verdana Bold.ttf",
        "DejaVuSans-Bold.ttf",
    )


def render_digit_template(
    digit: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    size: tuple[int, int],
) -> np.ndarray | None:
    canvas = Image.new("L", (140, 140), 0)
    draw = ImageDraw.Draw(canvas)
    bbox = draw.textbbox((0, 0), str(digit), font=font)
    draw.text((10 - bbox[0], 10 - bbox[1]), str(digit), font=font, fill=255)
    glyph_box = canvas.getbbox()
    if glyph_box is None:
        return None
    return np.asarray(canvas.crop(glyph_box).resize(size, Image.Resampling.NEAREST)) > 0


def pack_mask(mask: np.ndarray) -> tuple[int, int]:
    flat = np.ascontiguousarray(mask.reshape(-1), dtype=np.uint8)
    packed_bytes = np.packbits(flat, bitorder="little").tobytes()
    return int.from_bytes(packed_bytes, "little"), int(flat.sum())


def generated_templates(
    size: tuple[int, int], font_sizes: range, source_prefix: str
) -> list[DigitTemplate]:
    templates = []
    for font_path in font_paths():
        for font_size in font_sizes:
            try:
                font = ImageFont.truetype(font_path, font_size)
            except OSError:
                continue
            for digit in range(10):
                mask = render_digit_template(digit, font, size)
                if mask is not None:
                    packed, pixel_count = pack_mask(mask)
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
        mask = render_digit_template(digit, font, size)
        if mask is not None:
            packed, pixel_count = pack_mask(mask)
            templates.append(
                DigitTemplate(digit, packed, pixel_count, f"{source_prefix}:default")
            )
    return templates


def packed_jaccard(mask: int, pixel_count: int, template: DigitTemplate) -> float:
    intersection = (mask & template.mask).bit_count()
    union = pixel_count + template.pixel_count - intersection
    return float(intersection / union) if union else 0.0


class ScoreDigitReader:
    def __init__(self, templates: list[DigitTemplate] | None = None):
        self.templates = templates or generated_templates(
            SCORE_TEMPLATE_SIZE, range(28, 50, 4), "score-font"
        )

    def predict(self, image: Image.Image) -> DigitPrediction:
        mask_data = score_digit_mask(image)
        if mask_data is None:
            return DigitPrediction(
                None, 0.0, "none", None, score_digit_threshold(image)
            )
        normalized, threshold = mask_data
        packed, pixel_count = pack_mask(normalized)
        best_digit = None
        best_similarity = 0.0
        best_source = "none"
        for template in self.templates:
            similarity = packed_jaccard(packed, pixel_count, template)
            if similarity > best_similarity:
                best_digit = template.digit
                best_similarity = similarity
                best_source = template.source
        return DigitPrediction(
            best_digit, best_similarity, best_source, normalized, threshold
        )


class ScoreboardReader:
    def __init__(self, digit_reader: ScoreDigitReader | None = None):
        self.digit_reader = digit_reader or ScoreDigitReader()

    def read(self, image: Image.Image | None) -> ScoreReading:
        if image is None:
            return ScoreReading(None, (), (), False)
        boxes = score_cell_boxes(image.size)
        predictions = []
        has_layout = True
        for index, box in enumerate(boxes):
            cell = inner_cell(image.crop(box))
            if not score_cell_has_background(cell, index):
                has_layout = False
            predictions.append(self.digit_reader.predict(cell))
        if not has_layout or any(
            prediction.digit is None for prediction in predictions
        ):
            return ScoreReading(None, tuple(predictions), boxes, has_layout)
        return ScoreReading(
            tuple(prediction.digit for prediction in predictions),
            tuple(predictions),
            boxes,
            True,
        )


class TimerReader:
    def __init__(self):
        self.templates = generated_templates(
            TIMER_TEMPLATE_SIZE, range(44, 73, 4), "timer-font"
        )

    def state(self, image: Image.Image | None) -> str | None:
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
        dark_background = ((red < 60) & (green < 60) & (blue < 60)).mean()
        if red_background > 0.25:
            return "stopped"
        if green_foreground > 0.03 and dark_background > 0.30:
            return "running"
        return "blank"

    def threshold(self, image: Image.Image, state: str) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        red = rgb[:, :, 0]
        green = rgb[:, :, 1]
        blue = rgb[:, :, 2]
        if state == "stopped":
            return (red < 70) & (green < 70) & (blue < 70)
        return (green > 110) & (red < 120) & (blue < 130) & ((green - red) > 40)

    def predict_digit(self, mask: np.ndarray, threshold: np.ndarray) -> DigitPrediction:
        normalized = normalize_mask(mask, TIMER_TEMPLATE_SIZE)
        packed, pixel_count = pack_mask(normalized)
        best_digit = None
        best_similarity = 0.0
        best_source = "none"
        for template in self.templates:
            similarity = packed_jaccard(packed, pixel_count, template)
            if similarity > best_similarity:
                best_digit = template.digit
                best_similarity = similarity
                best_source = template.source
        return DigitPrediction(
            best_digit, best_similarity, best_source, normalized, threshold
        )

    def read(self, image: Image.Image | None) -> TimerReading:
        state = self.state(image)
        if image is None or state in (None, "blank"):
            return TimerReading(state, None, (), None)

        full_threshold = self.threshold(image, state)
        width, height = image.size
        display_left = int(width * 0.10)
        display_right = int(width * 0.74)
        display_bottom = int(height * 0.72)
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
                    int(area),
                    int(component_index),
                )
            )
        components.sort(key=lambda item: item[0])

        predictions = []
        for x, y, component_width, component_height, _, component_index in components:
            component_mask = (
                labels[
                    y : y + component_height,
                    x - display_left : x - display_left + component_width,
                ]
                == component_index
            )
            local_threshold = full_threshold[
                y : y + component_height, x : x + component_width
            ]
            predictions.append(self.predict_digit(component_mask, local_threshold))

        digits = [
            prediction.digit
            for prediction in predictions
            if prediction.digit is not None
        ]
        if len(digits) == 3:
            value = f"{digits[0]}:{digits[1]}{digits[2]}"
        elif len(digits) == 4:
            value = f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}"
        else:
            value = None
        return TimerReading(state, value, tuple(predictions), full_threshold)


def open_image(path: Path) -> Image.Image | None:
    if not path.exists():
        return None
    return Image.open(path).convert("RGB")


def read_frame(
    frames_dir: Path, second: int, scoreboard: ScoreboardReader, timer: TimerReader
) -> FrameReading:
    score_image = open_image(frames_dir / f"{second:09d}_score.jpg")
    timer_image = open_image(frames_dir / f"{second:09d}_timer.jpg")
    return FrameReading(second, scoreboard.read(score_image), timer.read(timer_image))


def score_text(score: ScoreReading) -> str:
    if score.digits is None:
        return "no-score"
    digits = "".join(str(digit) for digit in score.digits)
    return f"{digits[:3]}/{digits[3:]}"


def timer_text(timer: TimerReading) -> str:
    if timer.state in (None, "blank"):
        return "blank"
    if timer.value is None:
        return f"{timer.state} ?"
    return f"{timer.state} {timer.value}"


def reading_text(reading: FrameReading) -> str:
    return (
        f"second={reading.second} "
        f"score={score_text(reading.score)} "
        f"timer={timer_text(reading.timer)}"
    )


def save_mask(path: Path, mask: np.ndarray | None, scale: int = 1):
    if mask is None:
        return
    image = Image.fromarray(mask.astype("uint8") * 255, "L")
    if scale != 1:
        image = image.resize(
            (image.width * scale, image.height * scale), Image.Resampling.NEAREST
        )
    image.save(path)


def write_debug(frames_dir: Path, reading: FrameReading, debug_dir: Path):
    second_dir = debug_dir / f"{reading.second:09d}"
    second_dir.mkdir(parents=True, exist_ok=True)

    score_image = open_image(frames_dir / f"{reading.second:09d}_score.jpg")
    if score_image is not None:
        score_image.save(second_dir / "score_original.jpg")
        annotated = score_image.copy()
        draw = ImageDraw.Draw(annotated)
        for index, box in enumerate(reading.score.cell_boxes):
            draw.rectangle(box, outline="yellow", width=2)
            cell = inner_cell(score_image.crop(box))
            cell.save(second_dir / f"score_cell_{index}_{SCORE_FIELDS[index]}.jpg")
            prediction = reading.score.predictions[index]
            save_mask(
                second_dir / f"score_cell_{index}_{SCORE_FIELDS[index]}_threshold.png",
                prediction.threshold_mask,
                scale=3,
            )
            save_mask(
                second_dir / f"score_cell_{index}_{SCORE_FIELDS[index]}_normalized.png",
                prediction.normalized_mask,
                scale=6,
            )
            (
                second_dir / f"score_cell_{index}_{SCORE_FIELDS[index]}_prediction.txt"
            ).write_text(
                f"digit={prediction.digit}\n"
                f"similarity={prediction.similarity:.4f}\n"
                f"source={prediction.source}\n"
            )
        annotated.save(second_dir / "score_annotated.jpg")

    timer_image = open_image(frames_dir / f"{reading.second:09d}_timer.jpg")
    if timer_image is not None:
        timer_image.save(second_dir / "timer_original.jpg")
        save_mask(
            second_dir / "timer_threshold.png", reading.timer.threshold_mask, scale=3
        )
        for index, prediction in enumerate(reading.timer.predictions):
            save_mask(
                second_dir / f"timer_digit_{index}_normalized.png",
                prediction.normalized_mask,
                scale=6,
            )
            save_mask(
                second_dir / f"timer_digit_{index}_threshold.png",
                prediction.threshold_mask,
                scale=3,
            )
            (second_dir / f"timer_digit_{index}_prediction.txt").write_text(
                f"digit={prediction.digit}\n"
                f"similarity={prediction.similarity:.4f}\n"
                f"source={prediction.source}\n"
            )


def label_score_text(label: Label) -> str:
    if any(digit is None for digit in label.score_digits):
        return "no-score"
    digits = "".join(str(digit) for digit in label.score_digits)
    return f"{digits[:3]}/{digits[3:]}"


def test_labels(frames_dir: Path, labels: list[Label], debug_dir: Path | None) -> bool:
    scoreboard = ScoreboardReader()
    timer = TimerReader()
    score_ok = 0
    timer_state_ok = 0
    timer_value_ok = 0
    failures = []

    for label in labels:
        reading = read_frame(frames_dir, label.second, scoreboard, timer)
        print(reading_text(reading))
        if debug_dir is not None:
            write_debug(frames_dir, reading, debug_dir)

        expected_score = (
            None
            if any(digit is None for digit in label.score_digits)
            else tuple(digit for digit in label.score_digits if digit is not None)
        )
        if reading.score.digits == expected_score:
            score_ok += 1
        else:
            failures.append(
                f"second={label.second} score expected={label_score_text(label)} "
                f"actual={score_text(reading.score)}"
            )

        if reading.timer.state == label.timer_state:
            timer_state_ok += 1
        else:
            failures.append(
                f"second={label.second} timer_state expected={label.timer_state} "
                f"actual={reading.timer.state}"
            )

        if reading.timer.value == label.timer_value:
            timer_value_ok += 1
        else:
            failures.append(
                f"second={label.second} timer_value expected={label.timer_value} "
                f"actual={reading.timer.value}"
            )

    print(
        f"score_accuracy={score_ok}/{len(labels)} "
        f"timer_state_accuracy={timer_state_ok}/{len(labels)} "
        f"timer_value_accuracy={timer_value_ok}/{len(labels)}"
    )
    for failure in failures:
        print(f"FAIL {failure}")
    return not failures


def available_seconds(frames_dir: Path) -> list[int]:
    seconds = []
    for path in frames_dir.glob("*_score.jpg"):
        try:
            seconds.append(int(path.name.split("_", 1)[0]))
        except ValueError:
            continue
    return sorted(seconds)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--labels-csv", default=DEFAULT_LABELS_CSV, type=Path)
    parser.add_argument("--seconds", nargs="*", type=int)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--start", type=int)
    parser.add_argument("--end", type=int)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    labels = load_labels(args.labels_csv)
    if args.test:
        return 0 if test_labels(args.frames_dir, labels, args.debug_dir) else 1

    if args.all:
        seconds = available_seconds(args.frames_dir)
    elif args.seconds is not None:
        seconds = args.seconds
    else:
        seconds = [label.second for label in labels]

    if args.start is not None:
        seconds = [second for second in seconds if second >= args.start]
    if args.end is not None:
        seconds = [second for second in seconds if second <= args.end]
    if args.step > 1:
        seconds = [second for second in seconds if second % args.step == 0]

    scoreboard = ScoreboardReader()
    timer = TimerReader()
    started_at = time.perf_counter()
    for second in seconds:
        reading = read_frame(args.frames_dir, second, scoreboard, timer)
        if args.debug_dir is not None:
            write_debug(args.frames_dir, reading, args.debug_dir)
        if not args.quiet:
            print(reading_text(reading))
    elapsed = time.perf_counter() - started_at
    print(
        f"processed={len(seconds)} elapsed={elapsed:.3f}s fps={len(seconds) / elapsed:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
