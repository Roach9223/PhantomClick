"""Named-sequence preset store.

Saves the current Recorder step list as JSON under ``<config_dir>/sequences/<name>.json``
so the user can keep multiple bot configurations side-by-side and switch between
them without re-building from scratch.

The on-disk format is the same shape as ``config.json["recorder_steps"]`` — a
list of dicts produced by :meth:`RecorderStep.to_json` — so any sequence file
can also be inspected/edited by hand without going through the UI.

Track-step PNG templates are referenced by ``step_id``; the templates
themselves stay in ``templates/`` and aren't bundled into the sequence file
(too heavy, and they need to live next to the running app anyway). Loading a
sequence whose track templates were deleted will surface as broken Track
steps in the UI — same failure mode as a track step whose PNG was manually
removed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List

from modules.recorder import RecorderStep
from ui.config_io import _config_dir


_FILENAME_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sequences_dir() -> Path:
    """Where named sequences are stored. Created on demand."""
    d = _config_dir() / "sequences"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_name(name: str) -> str:
    """Strip filesystem-unsafe characters and collapse whitespace.

    Returns the cleaned name (without ``.json``). Empty / all-bad input
    returns ``''`` — caller should treat as invalid.
    """
    name = (name or "").strip()
    name = _FILENAME_BAD_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name)
    return name[:80]   # keep file names reasonable


def _path_for(name: str) -> Path:
    return sequences_dir() / f"{sanitize_name(name)}.json"


def list_sequences() -> List[dict]:
    """Return one entry per sequence file, sorted by saved-at descending.

    Each entry: ``{"name": str, "step_count": int, "saved_at": str}``.
    """
    out: list[dict] = []
    for p in sequences_dir().glob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                data = json.load(f)
            steps = data.get("steps", [])
            out.append({
                "name": p.stem,
                "step_count": len(steps) if isinstance(steps, list) else 0,
                "saved_at": data.get("saved_at", ""),
            })
        except Exception:
            # Skip unreadable / corrupt files rather than failing the whole listing.
            out.append({"name": p.stem, "step_count": 0, "saved_at": ""})
    out.sort(key=lambda e: e.get("saved_at", ""), reverse=True)
    return out


def exists(name: str) -> bool:
    return _path_for(name).exists()


def save_sequence(name: str, steps: list[RecorderStep]) -> Path:
    """Write ``steps`` to ``sequences/<name>.json``. Overwrites if present."""
    safe = sanitize_name(name)
    if not safe:
        raise ValueError("Sequence name is empty after sanitization.")
    path = _path_for(safe)
    payload = {
        "name": safe,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "step_count": len(steps),
        "steps": [s.to_json() for s in steps],
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return path


def load_sequence(name: str) -> list[RecorderStep]:
    """Read ``sequences/<name>.json`` and return as a fresh list of
    :class:`RecorderStep` instances. Skips entries that fail to deserialize
    (logs would be nice; for v1, silent skip).
    """
    path = _path_for(name)
    if not path.exists():
        raise FileNotFoundError(f"No sequence named '{name}'")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        return []
    out: list[RecorderStep] = []
    for entry in raw_steps:
        try:
            out.append(RecorderStep.from_json(entry))
        except Exception:
            continue
    return out


def delete_sequence(name: str) -> bool:
    """Delete the named sequence. Returns False if it didn't exist."""
    path = _path_for(name)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False
