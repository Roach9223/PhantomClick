"""Named-sequence preset store.

Saves the current Recorder step list as JSON under ``<config_dir>/sequences/<name>.json``
so the user can keep multiple bot configurations side-by-side and switch between
them without re-building from scratch.

The on-disk format is the same shape as ``config.json["recorder_steps"]``, a
list of dicts produced by :meth:`RecorderStep.to_json`, so any sequence file
can also be inspected/edited by hand without going through the UI.

Track-step PNG templates are embedded in presets. Loading restores fresh
copies so editing or clearing a sequence cannot damage its saved preset.
Legacy presets containing only image paths remain readable.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import List

from modules.recorder import RecorderStep, template_paths_of
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
    returns ``''``, caller should treat as invalid.
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
        "assets": {},
    }
    # Keep Track images in the preset so clearing the editor cannot break it.
    for step in steps:
        for template in template_paths_of(step):
            source = Path(template)
            if not source.is_absolute():
                source = _config_dir() / source
            payload["assets"][template] = base64.b64encode(source.read_bytes()).decode("ascii")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            json.dump(payload, f, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def load_sequence(name: str) -> list[RecorderStep]:
    """Read ``sequences/<name>.json`` and return as a fresh list of
    :class:`RecorderStep` instances. Invalid entries reject the whole preset.
    """
    path = _path_for(name)
    if not path.exists():
        raise FileNotFoundError(f"No sequence named '{name}'")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Sequence must contain a JSON object.")
    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError("Sequence steps must be a list.")
    out: list[RecorderStep] = []
    for entry in raw_steps:
        try:
            step = RecorderStep.from_json(entry)
            if step is None:
                raise ValueError("invalid step")
            out.append(step)
        except Exception as e:
            raise ValueError(f"Cannot load step {len(out) + 1}: {e}") from e
    assets = data.get("assets", {})
    if not isinstance(assets, dict):
        raise ValueError("Sequence assets must be an object.")
    decoded = {}
    from PIL import Image
    # Validate every embedded image before writing anything or replacing steps.
    for step in out:
        for template in template_paths_of(step):
            if template in assets:
                raw = base64.b64decode(assets[template], validate=True)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format != "PNG":
                        raise ValueError("Track assets must be PNG images")
                    image.verify()
                decoded[template] = raw
    restored = {}
    created = []
    try:
        root = _config_dir()
        for original, raw in decoded.items():
            destination = root / "templates" / f"preset_{uuid.uuid4().hex}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            created.append(destination)
            restored[original] = destination.relative_to(root).as_posix()
        for step in out:
            step.template_path = restored.get(step.template_path, step.template_path)
            step.extra_template_paths = [restored.get(p, p) for p in step.extra_template_paths]
    except Exception:
        for destination in created:
            destination.unlink(missing_ok=True)
        raise
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
