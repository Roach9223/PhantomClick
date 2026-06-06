"""Uptext parser — top-of-screen hover action text.

**Phase 2 stub.** Uptext rendering varies by graphics mode and requires a
different font (bold_12) than chatbox, plus calibration of the text ROI.
This module provides the API shape; the actual parser lands in Phase 4
once a bold_12 font is compiled and uptext positioning is calibrated.
"""

from __future__ import annotations

from typing import Optional

from .types import Uptext


def read_uptext(frame, prev_frame=None) -> Optional[Uptext]:
    """Parse the uptext region of `frame`.

    Returns `None` in Phase 2 — the real implementation lands alongside a
    compiled `bold_12.rvf` and a calibrated uptext ROI.
    """
    _ = (frame, prev_frame)
    return None
