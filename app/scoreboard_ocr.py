from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image


DEFAULT_SCOREBOARD_ROI = (0.0, 0.0, 0.23, 0.18)
DEFAULT_TIMER_ROI = (0.33, 0.0, 0.33, 0.09)
PADDLE_OCR_ENGINE = "paddleocr"
FAST_OCR_ENGINE = "opencv_rules"
DEFAULT_OVERLAY_STYLE = "auto"
OVERLAY_STYLES = ("auto", "new", "old")
SCORE_FIELDS = (
    "red_points",
    "red_advantages",
    "red_penalties",
    "blue_points",
    "blue_advantages",
    "blue_penalties",
)
NEW_SCORE_BOX_ROIS = {
    "red_points": (0.585, 0.10, 0.095, 0.34),
    "red_advantages": (0.715, 0.10, 0.095, 0.34),
    "red_penalties": (0.845, 0.10, 0.095, 0.34),
    "blue_points": (0.585, 0.58, 0.095, 0.32),
    "blue_advantages": (0.715, 0.58, 0.095, 0.32),
    "blue_penalties": (0.845, 0.58, 0.095, 0.32),
}
OLD_SCORE_BOX_ROIS = {
    "red_points": (0.515, 0.02, 0.16, 0.44),
    "red_advantages": (0.690, 0.02, 0.13, 0.44),
    "red_penalties": (0.840, 0.02, 0.13, 0.44),
    "blue_points": (0.515, 0.52, 0.16, 0.42),
    "blue_advantages": (0.690, 0.52, 0.13, 0.42),
    "blue_penalties": (0.840, 0.52, 0.13, 0.42),
}
SCORE_BOX_ROIS_BY_STYLE = {
    "new": NEW_SCORE_BOX_ROIS,
    "old": OLD_SCORE_BOX_ROIS,
}
NEW_NAME_ROIS = {
    "red_athlete_name": (0.015, 0.02, 0.54, 0.18),
    "red_team_name": (0.015, 0.17, 0.54, 0.16),
    "blue_athlete_name": (0.015, 0.55, 0.54, 0.18),
    "blue_team_name": (0.015, 0.70, 0.54, 0.16),
}
OLD_NAME_ROIS = {
    "red_athlete_name": (0.015, 0.02, 0.48, 0.20),
    "red_team_name": (0.015, 0.20, 0.48, 0.16),
    "blue_athlete_name": (0.015, 0.53, 0.48, 0.20),
    "blue_team_name": (0.015, 0.71, 0.48, 0.16),
}
NAME_ROIS_BY_STYLE = {
    "new": NEW_NAME_ROIS,
    "old": OLD_NAME_ROIS,
}
NAME_FIELDS = (
    "red_athlete_name",
    "red_team_name",
    "blue_athlete_name",
    "blue_team_name",
)


@dataclass(frozen=True)
class PaddleToken:
    text: str
    score: float
    box: list[int]

    @property
    def x_center(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def y_center(self) -> float:
        return (self.box[1] + self.box[3]) / 2


@dataclass(frozen=True)
class FrameOcrReading:
    frame_second: int
    frame_index: int
    video_offset_seconds: float
    ocr_engine: str
    overlay_style: str | None
    clock: str | None
    red_points: int | None
    red_advantages: int | None
    red_penalties: int | None
    blue_points: int | None
    blue_advantages: int | None
    blue_penalties: int | None
    red_athlete_name: str | None
    red_team_name: str | None
    blue_athlete_name: str | None
    blue_team_name: str | None
    known_score_count: int
    score_complete: bool
    clock_detected: bool
    victory: bool
    victory_text: str | None
    scoreboard_text: str
    timer_text: str


def build_paddle_ocr(lang: str = "en"):
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang=lang,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def pixel_roi(
    roi: tuple[float, float, float, float], image_width: int, image_height: int
) -> tuple[int, int, int, int]:
    x, y, width, height = roi
    left = int(round(x * image_width))
    top = int(round(y * image_height))
    crop_width = max(1, int(round(width * image_width)))
    crop_height = max(1, int(round(height * image_height)))
    return left, top, left + crop_width, top + crop_height


def cv_pixel_roi(
    roi: tuple[float, float, float, float], image_width: int, image_height: int
) -> tuple[int, int, int, int]:
    left, top, right, bottom = pixel_roi(roi, image_width, image_height)
    return left, top, max(1, right - left), max(1, bottom - top)


def crop_percent(
    image: np.ndarray, roi: tuple[float, float, float, float]
) -> np.ndarray:
    height, width = image.shape[:2]
    x, y, crop_width, crop_height = cv_pixel_roi(roi, width, height)
    return image[y : y + crop_height, x : x + crop_width]


def crop_pixels(
    image: np.ndarray, roi: tuple[float, float, float, float]
) -> np.ndarray:
    return crop_percent(image, roi)


def preprocess_for_white_digit(image: np.ndarray, scale: int = 6) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 145), (179, 110, 255))
    mask = cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return cv2.bitwise_not(mask)


def preprocess_for_text(image: np.ndarray, scale: int = 3) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )


def clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = text.strip(" |{}[]()<>\":'`~—-_:;,.")
    return text or ""


def ocr_text(image: np.ndarray, config: str = "--psm 7", scale: int = 3) -> str:
    try:
        import pytesseract
    except ImportError:
        return ""

    gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scaled = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return clean_ocr_text(pytesseract.image_to_string(scaled, config=config))


def ocr_name_text(image: np.ndarray) -> str:
    for scale in (3, 4, 2, 5):
        text = ocr_text(image, config="--psm 7", scale=scale)
        if len(text) >= 2:
            return text
    return ""


def parse_name_regions(
    scoreboard: np.ndarray,
    name_rois: dict[str, tuple[float, float, float, float]],
) -> dict[str, str | None]:
    names = {}
    for field, roi in name_rois.items():
        names[field] = ocr_name_text(crop_pixels(scoreboard, roi)) or None
    return names


def empty_names() -> dict[str, str | None]:
    return {field: None for field in NAME_FIELDS}


def names_to_scoreboard_text(names: dict[str, str | None]) -> str:
    return "\n".join(names[field] for field in NAME_FIELDS if names.get(field))


def ocr_digit(image: np.ndarray) -> int | None:
    foreground = image < 128
    count, _, stats, _ = cv2.connectedComponentsWithStats(foreground.astype("uint8"), 8)
    components: list[tuple[int, int, int, int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area > 100:
            components.append((int(x), int(y), int(width), int(height), int(area)))
    if not components:
        return None

    x, y, width, height, _ = max(components, key=lambda component: component[4])
    if height <= 0:
        return None
    if width / height < 0.50:
        return 1

    digit = foreground[y : y + height, x : x + width].astype("uint8") * 255
    return classify_clock_digit(digit)


def score_state_values(state: dict[str, int | None]) -> tuple[int | None, ...]:
    return tuple(state[field] for field in SCORE_FIELDS)


def known_score_count(state: dict[str, int | None]) -> int:
    return sum(value is not None for value in score_state_values(state))


def state_complete(state: dict[str, int | None]) -> bool:
    return all(value is not None for value in score_state_values(state))


def parse_score_boxes(
    scoreboard: np.ndarray,
    score_box_rois: dict[str, tuple[float, float, float, float]],
) -> dict[str, int | None]:
    digits = {}
    for field, box_roi in score_box_rois.items():
        box_crop = crop_pixels(scoreboard, box_roi)
        box_processed = preprocess_for_white_digit(box_crop)
        digits[field] = ocr_digit(box_processed)
    return digits


def choose_score_state(
    scoreboard: np.ndarray, overlay_style: str
) -> tuple[str | None, dict[str, int | None]]:
    styles = ("new", "old") if overlay_style == "auto" else (overlay_style,)
    candidates = [
        (style, parse_score_boxes(scoreboard, SCORE_BOX_ROIS_BY_STYLE[style]))
        for style in styles
    ]
    return max(candidates, key=lambda candidate: known_score_count(candidate[1]))


def preprocess_green_clock(timer: np.ndarray, scale: int = 3) -> np.ndarray:
    _, width = timer.shape[:2]
    clock = timer[:, : int(width * 0.55)]
    hsv = cv2.cvtColor(clock, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 80, 80), (95, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def preprocess_dark_clock(timer: np.ndarray, scale: int = 3) -> np.ndarray:
    _, width = timer.shape[:2]
    clock = timer[:, : int(width * 0.55)]
    gray = cv2.cvtColor(clock, cv2.COLOR_BGR2GRAY)
    mask = cv2.inRange(gray, 0, 70)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return cv2.resize(mask, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def _stroke_features(digit_mask: np.ndarray) -> dict[str, float]:
    digit = digit_mask > 0
    height, width = digit.shape
    return {
        "fill": float(digit.mean()),
        "width_ratio": width / height,
        "top": float(
            digit[0 : int(0.18 * height), int(0.25 * width) : int(0.75 * width)].mean()
        ),
        "mid": float(
            digit[
                int(0.40 * height) : int(0.60 * height),
                int(0.25 * width) : int(0.75 * width),
            ].mean()
        ),
        "bot": float(
            digit[int(0.82 * height) :, int(0.25 * width) : int(0.75 * width)].mean()
        ),
        "ul": float(
            digit[int(0.18 * height) : int(0.45 * height), : int(0.35 * width)].mean()
        ),
        "ur": float(
            digit[int(0.18 * height) : int(0.45 * height), int(0.65 * width) :].mean()
        ),
        "ll": float(
            digit[int(0.55 * height) : int(0.82 * height), : int(0.35 * width)].mean()
        ),
        "lr": float(
            digit[int(0.55 * height) : int(0.82 * height), int(0.65 * width) :].mean()
        ),
    }


def classify_clock_digit(digit_mask: np.ndarray) -> int | None:
    f = _stroke_features(digit_mask)

    if f["width_ratio"] < 0.55 or (
        f["ul"] < 0.10 and f["ll"] < 0.10 and f["ur"] > 0.80 and f["lr"] > 0.80
    ):
        return 1
    if f["ll"] < 0.15 and f["lr"] > 0.60 and f["mid"] > 0.75:
        return 9
    if f["top"] > 0.80 and f["bot"] > 0.80 and f["ur"] > 0.65 and f["lr"] < 0.25:
        return 2
    if f["ll"] < 0.20 and f["lr"] < 0.25:
        if f["bot"] > 0.80:
            return 2
        return 7
    if f["fill"] > 0.68 and f["mid"] > 0.60:
        return 8
    if (
        f["top"] > 0.75
        and f["mid"] > 0.65
        and f["bot"] > 0.75
        and f["ur"] > 0.65
        and f["lr"] > 0.65
        and f["ul"] < 0.50
        and f["ll"] < 0.50
    ):
        return 3
    if (
        f["mid"] > 0.40
        and f["ur"] < 0.75
        and f["ul"] > 0.75
        and f["ll"] > 0.75
        and f["lr"] > 0.75
    ):
        return 6
    if f["mid"] < 0.50 and f["ul"] > 0.75 and f["ll"] > 0.75 and f["lr"] > 0.75:
        return 0
    if f["bot"] < 0.50 and f["mid"] > 0.60:
        return 4
    if f["ul"] < 0.20 and f["ur"] > 0.60 and f["ll"] > 0.40 and f["bot"] > 0.80:
        return 3 if f["lr"] > 0.50 else 2
    if f["ur"] < 0.45 and f["ul"] > 0.50 and f["ll"] > 0.50 and f["lr"] > 0.50:
        return 6
    if f["ul"] > 0.70 and f["lr"] > 0.80 and f["bot"] > 0.80:
        return 5
    return None


def parse_clock_mask(mask: np.ndarray) -> str | None:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    min_area = max(25, int(mask.shape[0] * mask.shape[1] * 0.02))
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area > min_area and height > mask.shape[0] * 0.50:
            boxes.append((int(x), int(y), int(width), int(height), int(area)))

    boxes = sorted(boxes, key=lambda box: box[0])[:4]
    if len(boxes) not in (3, 4):
        return None

    digits = []
    for x, y, width, height, _ in boxes:
        digit = mask[y : y + height, x : x + width]
        parsed = classify_clock_digit(digit)
        if parsed is None:
            return None
        digits.append(parsed)

    if len(digits) == 3:
        return f"{digits[0]}:{digits[1]}{digits[2]}"
    return f"{digits[0]}{digits[1]}:{digits[2]}{digits[3]}"


def parse_green_clock(timer: np.ndarray) -> str | None:
    return parse_clock_mask(preprocess_green_clock(timer, scale=1))


def parse_dark_clock(timer: np.ndarray) -> str | None:
    return parse_clock_mask(preprocess_dark_clock(timer, scale=1))


def parse_clock_text(text: str) -> str | None:
    match = re.search(r"\b(\d{1,2})\s*[:;]\s*(\d{2})\b", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    return None


def ocr_timer_clock(timer: np.ndarray) -> tuple[str | None, str]:
    timer_processed = preprocess_for_text(timer)
    text = ocr_text(timer_processed, config="--psm 6", scale=1)
    return parse_clock_text(text), text


def write_fast_debug_images(
    debug_dir: Path,
    frame_name: str,
    scoreboard: np.ndarray,
    timer: np.ndarray,
    selected_style: str | None,
    score_state: dict[str, int | None],
    names: dict[str, str | None],
    clock: str | None,
    timer_text: str,
) -> None:
    frame_dir = debug_dir / Path(frame_name).stem
    frame_dir.mkdir(parents=True, exist_ok=True)
    green_clock = preprocess_green_clock(timer)
    dark_clock = preprocess_dark_clock(timer)
    cv2.imwrite(str(frame_dir / "scoreboard.jpg"), scoreboard)
    cv2.imwrite(str(frame_dir / "timer.jpg"), timer)
    cv2.imwrite(str(frame_dir / "green_clock_mask.jpg"), cv2.bitwise_not(green_clock))
    cv2.imwrite(str(frame_dir / "dark_clock_mask.jpg"), cv2.bitwise_not(dark_clock))
    (frame_dir / "reading.json").write_text(
        json.dumps(
            {
                "overlay_style": selected_style,
                "score_state": score_state,
                "names": names,
                "clock": clock,
                "timer_text": timer_text,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def crop_frame(
    frame_path: Path,
    output_path: Path,
    roi: tuple[float, float, float, float],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(frame_path) as image:
        crop = image.crop(pixel_roi(roi, image.width, image.height))
        crop.save(output_path)


def result_tokens(result: dict[str, Any] | None) -> list[PaddleToken]:
    if not result:
        return []

    texts = result.get("rec_texts") or []
    scores = result.get("rec_scores") or []
    boxes = result.get("rec_boxes")
    if boxes is None:
        boxes = []
    if hasattr(boxes, "tolist"):
        boxes = boxes.tolist()

    tokens = []
    for text, score, box in zip(texts, scores, boxes):
        if len(box) != 4:
            continue
        tokens.append(
            PaddleToken(
                text=str(text).strip(),
                score=float(score),
                box=[int(round(value)) for value in box],
            )
        )
    return [token for token in tokens if token.text]


def run_ocr(ocr, image_path: Path) -> dict[str, Any] | None:
    results = ocr.predict(str(image_path))
    if not results:
        return None
    return results[0]


def tokens_text(tokens: list[PaddleToken]) -> str:
    lines = sorted(tokens, key=lambda token: (token.y_center, token.x_center))
    return "\n".join(token.text for token in lines)


def parse_clock(tokens: list[PaddleToken]) -> str | None:
    for token in tokens:
        match = re.search(r"\b(\d{1,2})\s*[:;]\s*(\d{2})\b", token.text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return None


def parse_score_state(tokens: list[PaddleToken]) -> dict[str, int | None]:
    digit_tokens = [
        token
        for token in tokens
        if re.fullmatch(r"\d{1,2}", token.text.strip()) and token.score >= 0.50
    ]
    if len(digit_tokens) < 6:
        return {field: None for field in SCORE_FIELDS}

    digit_tokens = sorted(digit_tokens, key=lambda token: token.y_center)
    split = len(digit_tokens) // 2
    top_row = sorted(digit_tokens[:split], key=lambda token: token.x_center)[-3:]
    bottom_row = sorted(digit_tokens[split:], key=lambda token: token.x_center)[-3:]
    ordered = top_row + bottom_row

    parsed = {}
    for field, token in zip(SCORE_FIELDS, ordered):
        parsed[field] = int(token.text)
    return parsed


def _tokens_by_line(tokens: list[PaddleToken], line_tolerance: float = 12.0):
    lines: list[list[PaddleToken]] = []
    for token in sorted(tokens, key=lambda item: item.y_center):
        for line in lines:
            center = sum(item.y_center for item in line) / len(line)
            if abs(token.y_center - center) <= line_tolerance:
                line.append(token)
                break
        else:
            lines.append([token])
    return [sorted(line, key=lambda item: item.x_center) for line in lines]


def parse_paddle_names(tokens: list[PaddleToken]) -> dict[str, str | None]:
    text_tokens = [
        token
        for token in tokens
        if token.score >= 0.35 and not re.fullmatch(r"\d{1,2}", token.text.strip())
    ]
    if not text_tokens:
        return empty_names()

    max_bottom = max(token.box[3] for token in tokens)
    max_right = max(token.box[2] for token in tokens)
    left_tokens = [token for token in text_tokens if token.x_center <= max_right * 0.58]
    top_tokens = [token for token in left_tokens if token.y_center < max_bottom * 0.50]
    bottom_tokens = [
        token for token in left_tokens if token.y_center >= max_bottom * 0.50
    ]

    names = empty_names()
    for prefix, row_tokens in (("red", top_tokens), ("blue", bottom_tokens)):
        lines = [
            clean_ocr_text(" ".join(token.text for token in line))
            for line in _tokens_by_line(row_tokens)
        ]
        lines = [line for line in lines if line]
        if lines:
            names[f"{prefix}_athlete_name"] = lines[0]
        if len(lines) > 1:
            names[f"{prefix}_team_name"] = lines[1]
    return names


def parse_victory_text(scoreboard_text: str) -> str | None:
    lines = [line.strip() for line in scoreboard_text.splitlines() if line.strip()]
    if not lines or not re.search(r"\bvictory\b", lines[0], re.I):
        return None
    return "\n".join(lines)


def process_frame_paddle(
    ocr,
    frame_path: Path,
    frame_index: int,
    frame_second: int,
    crops_dir: Path,
    scoreboard_roi: tuple[float, float, float, float] = DEFAULT_SCOREBOARD_ROI,
    timer_roi: tuple[float, float, float, float] = DEFAULT_TIMER_ROI,
) -> FrameOcrReading:
    scoreboard_crop = crops_dir / "scoreboard" / frame_path.name
    timer_crop = crops_dir / "timer" / frame_path.name
    crop_frame(frame_path, scoreboard_crop, scoreboard_roi)
    crop_frame(frame_path, timer_crop, timer_roi)

    scoreboard_tokens = result_tokens(run_ocr(ocr, scoreboard_crop))
    timer_tokens = result_tokens(run_ocr(ocr, timer_crop))
    score_state = parse_score_state(scoreboard_tokens)
    names = parse_paddle_names(scoreboard_tokens)
    scoreboard_text = tokens_text(scoreboard_tokens)
    timer_text = tokens_text(timer_tokens)
    clock = parse_clock(timer_tokens)
    victory_text = parse_victory_text(scoreboard_text)

    return FrameOcrReading(
        frame_second=frame_second,
        frame_index=frame_index,
        video_offset_seconds=float(frame_second),
        ocr_engine=PADDLE_OCR_ENGINE,
        overlay_style=PADDLE_OCR_ENGINE,
        clock=clock,
        red_points=score_state["red_points"],
        red_advantages=score_state["red_advantages"],
        red_penalties=score_state["red_penalties"],
        blue_points=score_state["blue_points"],
        blue_advantages=score_state["blue_advantages"],
        blue_penalties=score_state["blue_penalties"],
        red_athlete_name=names["red_athlete_name"],
        red_team_name=names["red_team_name"],
        blue_athlete_name=names["blue_athlete_name"],
        blue_team_name=names["blue_team_name"],
        known_score_count=known_score_count(score_state),
        score_complete=state_complete(score_state),
        clock_detected=clock is not None,
        victory=victory_text is not None,
        victory_text=victory_text,
        scoreboard_text=scoreboard_text,
        timer_text=timer_text,
    )


def process_frame_fast(
    frame_path: Path,
    frame_index: int,
    frame_second: int,
    scoreboard_roi: tuple[float, float, float, float] = DEFAULT_SCOREBOARD_ROI,
    timer_roi: tuple[float, float, float, float] = DEFAULT_TIMER_ROI,
    overlay_style: str = DEFAULT_OVERLAY_STYLE,
    clock_fallback_ocr: bool = False,
    debug_dir: Path | None = None,
) -> FrameOcrReading:
    image = cv2.imread(str(frame_path))
    if image is None:
        return FrameOcrReading(
            frame_second=frame_second,
            frame_index=frame_index,
            video_offset_seconds=float(frame_second),
            ocr_engine=FAST_OCR_ENGINE,
            overlay_style=None,
            clock=None,
            red_points=None,
            red_advantages=None,
            red_penalties=None,
            blue_points=None,
            blue_advantages=None,
            blue_penalties=None,
            red_athlete_name=None,
            red_team_name=None,
            blue_athlete_name=None,
            blue_team_name=None,
            known_score_count=0,
            score_complete=False,
            clock_detected=False,
            victory=False,
            victory_text=None,
            scoreboard_text="",
            timer_text="",
        )

    scoreboard = crop_percent(image, scoreboard_roi)
    timer = crop_percent(image, timer_roi)
    selected_style, score_state = choose_score_state(scoreboard, overlay_style)
    names = parse_name_regions(
        scoreboard,
        NAME_ROIS_BY_STYLE.get(selected_style or "new", NEW_NAME_ROIS),
    )
    clock = parse_green_clock(timer) or parse_dark_clock(timer)
    timer_text = clock or ""
    if clock is None and clock_fallback_ocr:
        clock, timer_text = ocr_timer_clock(timer)
    if debug_dir is not None:
        write_fast_debug_images(
            debug_dir,
            frame_path.name,
            scoreboard,
            timer,
            selected_style,
            score_state,
            names,
            clock,
            timer_text,
        )
    scoreboard_text = names_to_scoreboard_text(names)

    return FrameOcrReading(
        frame_second=frame_second,
        frame_index=frame_index,
        video_offset_seconds=float(frame_second),
        ocr_engine=FAST_OCR_ENGINE,
        overlay_style=selected_style,
        clock=clock,
        red_points=score_state["red_points"],
        red_advantages=score_state["red_advantages"],
        red_penalties=score_state["red_penalties"],
        blue_points=score_state["blue_points"],
        blue_advantages=score_state["blue_advantages"],
        blue_penalties=score_state["blue_penalties"],
        red_athlete_name=names["red_athlete_name"],
        red_team_name=names["red_team_name"],
        blue_athlete_name=names["blue_athlete_name"],
        blue_team_name=names["blue_team_name"],
        known_score_count=known_score_count(score_state),
        score_complete=state_complete(score_state),
        clock_detected=clock is not None,
        victory=False,
        victory_text=None,
        scoreboard_text=scoreboard_text,
        timer_text=timer_text,
    )


# Backwards-compatible alias for tests and callers that predate engine selection.
process_frame = process_frame_paddle
