"""Frame replay source for the bot runner.

Lets the runner consume a sequence of saved frames (PNG files in a
directory, or a single PNG) instead of live ``mss`` capture. Used by
the AI tab's "▶ Replay" button to iterate on procedures without the
game running — feed it a ``runs/<session>/failures/`` directory and
the bot ticks against the same frames the user last saw fail.

The replay source matches the runner's ``_capture()`` contract:
``next_frame()`` returns a ``np.ndarray`` (HxWx3, BGR, uint8,
C-contiguous) or ``None`` when exhausted. The runner stops cleanly on
None so a finite replay finishes the session naturally.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np


_PNG_EXTS = (".png", ".PNG")


class FrameReplay:
    """Iterates over PNG frames found at a path.

    ``path`` may be:
    - A single ``.png`` file → yields it once, then None.
    - A directory → yields every ``.png`` inside, sorted by name, then
      None. Recurses one level so ``runs/<session>/failures/`` and
      similar nested layouts work without glob fiddling.

    Each frame is loaded once on first access and cached in memory —
    the typical replay set is a handful of failure frames or one
    fishing-spot recording, so RAM pressure is fine. If we ever ship
    multi-thousand-frame video replay we'll swap to lazy decode.
    """

    def __init__(self, path: str | Path, *, loop: bool = False) -> None:
        self._path = Path(path)
        self._loop = bool(loop)
        self._frames: List[np.ndarray] = []
        self._idx = 0
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        files: List[Path] = []
        p = self._path
        if not p.exists():
            return
        if p.is_file() and p.suffix in _PNG_EXTS:
            files = [p]
        elif p.is_dir():
            # Sorted top-level + one level deep.
            files = sorted(
                [f for f in p.iterdir() if f.is_file() and f.suffix in _PNG_EXTS]
            )
            if not files:
                files = sorted(
                    [f for f in p.glob("*/*") if f.is_file() and f.suffix in _PNG_EXTS]
                )
        from ..algorithms.bitmap import load_png
        for f in files:
            try:
                arr = load_png(f)
            except Exception:
                continue
            if arr is None or arr.ndim != 3 or arr.shape[2] < 3:
                continue
            self._frames.append(np.ascontiguousarray(arr[:, :, :3]))

    @property
    def frame_count(self) -> int:
        self._load()
        return len(self._frames)

    def next_frame(self) -> Optional[np.ndarray]:
        """Return the next frame in the sequence, or None when done."""
        self._load()
        if not self._frames:
            return None
        if self._idx >= len(self._frames):
            if self._loop:
                self._idx = 0
            else:
                return None
        frame = self._frames[self._idx]
        self._idx += 1
        return frame
