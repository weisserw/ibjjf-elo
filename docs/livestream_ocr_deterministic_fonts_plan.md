# Livestream OCR Deterministic Font Plan

## Goal

Make fixed-digit livestream OCR behave the same in local development, tests, and production by removing dependence on host-installed system fonts.

## Problem

`app/livestream_frame_text_ocr.py` currently generates digit templates from whatever fonts are available at runtime. Local macOS runs may use Arial/Verdana, while the production scanner Docker image is based on `python:3.11-slim` and likely does not have those fonts. That means the same timer frame can be classified with different templates in different environments, making regressions hard to reproduce.

## Plan

1. Add repo-owned OCR fonts.

   Use a small set of open fonts with redistribution-friendly licenses, for example:

   - `DejaVuSans-Bold.ttf`
   - `LiberationSans-Bold.ttf`
   - optionally `Roboto-Bold.ttf`

   Store them under:

   ```text
   app/ocr_fonts/
   ```

   Add `app/ocr_fonts/README.md` with font source and license notes.

2. Change `_font_paths()` to use only bundled fonts.

   Replace system paths like macOS Arial/Verdana and generic `DejaVuSans-Bold.ttf` lookup with repo-relative paths:

   ```python
   OCR_FONT_DIR = Path(__file__).resolve().parent / "ocr_fonts"

   def _font_paths() -> tuple[str, ...]:
       return tuple(str(path) for path in sorted(OCR_FONT_DIR.glob("*.ttf")))
   ```

3. Remove nondeterministic fallback fonts.

   In `_generated_templates()`, do not fall back to `ImageFont.load_default()`. If no bundled templates can be generated, raise a clear error:

   ```python
   raise RuntimeError(f"no OCR digit fonts found in {OCR_FONT_DIR}")
   ```

   This makes missing fonts fail loudly instead of silently changing OCR behavior.

4. Add tests for deterministic template sources.

   Add a unit test that builds a `TimerDigitReader()` and asserts:

   - no template source contains `default`
   - no template source starts with `/System/`
   - expected bundled font filenames appear in template sources

5. Keep image fixture regressions.

   Keep or add OCR fixture cases for:

   - `new_timer_0237.jpg` -> `running 2:37`
   - `new_timer_1000.jpg` -> `stopped 10:00`

   Keep the scanner regression that timer-only running OCR jitter does not emit sparse change events.

6. Confirm Docker behavior.

   If fonts live under `app/ocr_fonts/`, the existing scanner Dockerfile should include them through:

   ```dockerfile
   COPY app ./app
   ```

   No Debian font package should be required for fixed-digit OCR after this. `tesseract-ocr` remains required for name OCR.

7. Verify locally and in Docker.

   Run from the repository root:

   ```bash
   make test
   ```

   Then verify the scanner image:

   ```bash
   docker build -f Dockerfile.livestream-frame-text-scanner -t livestream-ocr-test .
   docker run --rm livestream-ocr-test python -m unittest app.tests.test_livestream_frame_text_scan.LivestreamFrameTextOcrFixtureTestCase
   ```

8. Optional hardening.

   Log fixed-digit OCR font sources at scanner startup or include them in debug output. Keep this concise, for example one line listing bundled font filenames. This makes future environment drift visible immediately.

## Expected Outcome

The fixed-digit OCR template set becomes deterministic. A fixture that passes locally should use the same digit templates in production, making timer OCR regressions reproducible and testable across installations.
