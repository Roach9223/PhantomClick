"""Block catalog — every executable node in the Studio.

Each block is a subclass of `Block` (see ``base.py``). Blocks register
themselves into the `REGISTRY` on import, and are categorised by their
module name (``flow``, ``vision``, ``color``, ``input``, etc.).

The node editor reads `REGISTRY` to populate the sidebar; the runtime
dispatches block execution via the same keys.
"""

from __future__ import annotations

# Import each category module so side-effect registrations populate
# `base.REGISTRY`. Adding a new category = one more import line here.
from . import bitmap as _bitmap  # noqa: F401
from . import color as _color  # noqa: F401
from . import dtm as _dtm  # noqa: F401
from . import feature as _feature  # noqa: F401
from . import flow as _flow    # noqa: F401
from . import input as _input  # noqa: F401
from . import ocr as _ocr  # noqa: F401
from . import tpa as _tpa      # noqa: F401
from . import vision as _vision  # noqa: F401

from .base import (  # noqa: E402
    REGISTRY,
    Block,
    Param,
    Port,
    iter_by_category,
    make_ngq_node_cls,
    read_param,
)

__all__ = [
    "REGISTRY",
    "Block",
    "Param",
    "Port",
    "iter_by_category",
    "make_ngq_node_cls",
    "read_param",
]
