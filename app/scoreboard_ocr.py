from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_SCOREBOARD_ROI = (0.0, 0.0, 0.23, 0.18)
DEFAULT_TIMER_ROI = (0.33, 0.0, 0.33, 0.09)
OCR_ENGINE = "paddleocr"
SCORE_FIELDS = (
    "red_points",
    "red_advantages",
    "red_penalties",
    "blue_points",
    "blue_advantages",
    "blue_penalties",
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


def parse_victory_text(scoreboard_text: str) -> str | None:
    lines = [line.strip() for line in scoreboard_text.splitlines() if line.strip()]
    if not lines or not re.search(r"\bvictory\b", lines[0], re.I):
        return None
    return "\n".join(lines)


def process_frame(
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
    scoreboard_text = tokens_text(scoreboard_tokens)
    timer_text = tokens_text(timer_tokens)
    victory_text = parse_victory_text(scoreboard_text)

    return FrameOcrReading(
        frame_second=frame_second,
        frame_index=frame_index,
        video_offset_seconds=float(frame_second),
        ocr_engine=OCR_ENGINE,
        overlay_style=OCR_ENGINE,
        clock=parse_clock(timer_tokens),
        red_points=score_state["red_points"],
        red_advantages=score_state["red_advantages"],
        red_penalties=score_state["red_penalties"],
        blue_points=score_state["blue_points"],
        blue_advantages=score_state["blue_advantages"],
        blue_penalties=score_state["blue_penalties"],
        victory=victory_text is not None,
        victory_text=victory_text,
        scoreboard_text=scoreboard_text,
        timer_text=timer_text,
    )
