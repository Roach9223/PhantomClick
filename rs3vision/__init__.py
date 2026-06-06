"""rs3vision — modern RS3 vision toolkit.

Clean-room Rust port of the algorithms pioneered by Simba/SRL, exposed to
Python with NumPy zero-copy interop.

Phase 1 surface:
    rs3vision.color.find(frame, target, cts=CTS.CTS2, tol=10, roi=None, ...)
    rs3vision.color.count(frame, target, cts=CTS.CTS2, tol=10, roi=None, ...)
    rs3vision.tpa.cluster(points, dist=1)
    rs3vision.tpa.bounds(points)
    rs3vision.tpa.centroid(points)
    rs3vision.tpa.filter_size(clusters, min, max)
    rs3vision.tpa.dilate(points, radius=1)
    rs3vision.tpa.erode(points, radius=1)
    rs3vision.CTS.CTS1 / CTS2 / CTS3

Frames are NumPy arrays of shape `(H, W, 3)` dtype=uint8 in BGR channel
order — the native layout of Win32 BitBlt captures.
"""

from __future__ import annotations

from . import _rs3vision
from . import chat_config
from . import chat as _chat
from . import types
from . import uptext as _uptext
from . import xp_drops as _xp_drops
from .chat_config import (
    ChatConfig,
    ChatDefaults,
    ChatEventSpec,
    ChatRoi,
    load_chat_config,
)

# High-level domain parsers.
chatbox_events = _chat.chatbox_events
read_uptext = _uptext.read_uptext
read_xp_drops = _xp_drops.read_xp_drops

# Submodules (zero-cost re-exports of the native module's submodules).
color = _rs3vision.color
tpa = _rs3vision.tpa
feature = _rs3vision.feature
ocr = _rs3vision.ocr
CTS = _rs3vision.CTS

# Confidence thresholds — keep in sync with rs3vision/templates/confidence.toml
# once the tuner produces one (Phase 6).
HIGH_CONF: float = 0.85
MED_CONF: float = 0.65
LOW_CONF: float = 0.50

__all__ = [
    "__version__",
    "color",
    "tpa",
    "feature",
    "ocr",
    "CTS",
    "types",
    "chat_config",
    "ChatConfig",
    "ChatDefaults",
    "ChatEventSpec",
    "ChatRoi",
    "load_chat_config",
    "chatbox_events",
    "read_uptext",
    "read_xp_drops",
    "HIGH_CONF",
    "MED_CONF",
    "LOW_CONF",
]

__version__: str = _rs3vision.__version__
