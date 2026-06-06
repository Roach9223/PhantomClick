"""Human-like mouse movement, clicking, and timing — ported from
PhantomClick (``F:\\.programs\\AutoClicker``).

The core algorithms are pure math and have zero OS-level dependencies:

- :mod:`rs3vision_studio.humanize.paths` — Wind/Hooke particle-sim path
  generator, cubic Bezier fallback, ease-in-out walking.
- :mod:`rs3vision_studio.humanize.fatigue` — session-scoped multiplier
  that drifts upward over time, plus randomized break-burst scheduling.
- :mod:`rs3vision_studio.humanize.anti_cluster` — force-repulsion push
  that nudges new targets away from recent click positions so multiple
  clicks don't land in an obvious grid.
- :mod:`rs3vision_studio.humanize.safeguards` — emergency-stop watchdog
  (cursor-to-corner → stop).

All modules accept a :class:`HumanizerConfig` so the Studio's Settings
dialog and per-task YAML ``params`` can tweak the feel without editing
code.

Integration note: the mouse controller is injected (see
:class:`MouseAPI`) so we can route through the Studio's existing input
backend rather than punching pynput directly. That keeps a single
source of truth for "how do we actually move the cursor" and lets the
``post_message`` backend (once implemented) benefit from the same
humanization layer.
"""

from __future__ import annotations

from .config import HumanizerConfig
from .fatigue import Fatigue
from .mouse_api import MouseAPI, PynputMouse

__all__ = [
    "HumanizerConfig",
    "Fatigue",
    "MouseAPI",
    "PynputMouse",
]
