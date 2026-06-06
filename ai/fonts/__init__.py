"""Compiled bitmap fonts for the rs3vision OCR engine.

Ships:
- ``plain_11.rvf`` — the RS3 NXT uptext / chatbox font, compiled from
  our captured corpus via ``rs3vision-tools/build_uptext_font.py``.

File is binary (``.rvf``) and lives in the same directory. If it
doesn't exist yet, the uptext reader gracefully disables itself and
logs a clear message pointing at the build script.
"""

from __future__ import annotations

from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent
UPTEXT_FONT_PATH = FONTS_DIR / "plain_11.rvf"


def uptext_font_ready() -> bool:
    """True iff the uptext font has been built and shipped."""
    return UPTEXT_FONT_PATH.exists()
