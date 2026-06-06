"""XP-drop parser — scrolling skill XP notifications.

**Phase 2 stub.** XP drops are at a configurable on-screen position, use
a small font (`small_08`), and require per-skill icon anchors. Shipped as
API shape only; the real implementation lands in Phase 4 alongside
`small_08.rvf` and the skill-icon calibration flow.
"""

from __future__ import annotations

from typing import List

from .types import XpDrop


def read_xp_drops(frame, prev_frame=None) -> List[XpDrop]:
    """Parse XP drops from `frame`. Empty list in the Phase 2 stub."""
    _ = (frame, prev_frame)
    return []
