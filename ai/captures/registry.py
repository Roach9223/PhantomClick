"""Read + promote API for the global capture library at
``ai/captures/global/``.

The on-disk layout mirrors a bot bundle's ``assets/`` directory so the
promote operation is a straight file copy — no schema rewrite::

    ai/captures/global/
    ├── colors/
    │   ├── seren_spirit_halo.json     # {"slug","name","rgb",[...]}
    │   └── index.json                  # [{slug, name, rgb, ...}, ...]
    ├── snapshots/
    │   ├── bank_open_vip.png
    │   └── index.json                  # [{slug, name, rect, ...}, ...]
    └── recordings/
        └── player_fishing/
            ├── frame_000.png
            ├── frame_001.png
            ├── ...
            └── meta.json

Lookups raise :class:`KeyError` when the named asset isn't present in
the global library — bots resolve names eagerly at module import so a
missing capture surfaces as a clean import-time failure, not a tick
mid-run.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# The global library lives under the writable install root so promoted
# captures persist next to the .exe in a frozen build (a ``_MEIPASS``-
# relative path would be wiped on exit). In dev this resolves to
# <repo>/ai/captures/global. The dir is created on first access by
# ``_ensure_root`` — no seed files need to ship.
from utils.paths import writable_root

_ROOT = writable_root() / "ai" / "captures" / "global"


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Match :func:`ai.bot.bundle.slugify` so promoted assets keep
    their bundle name verbatim."""
    s = _SLUG_RE.sub("_", name.lower()).strip("_")
    return s or "unnamed"


def _ensure_root() -> Path:
    for sub in ("colors", "snapshots", "recordings", "dtms", "rois"):
        (_ROOT / sub).mkdir(parents=True, exist_ok=True)
    return _ROOT


# ── Public read API ─────────────────────────────────────────────────


def root() -> Path:
    """Return (and ensure) the global capture root."""
    return _ensure_root()


def colors_dir() -> Path:
    return _ensure_root() / "colors"


def snapshots_dir() -> Path:
    return _ensure_root() / "snapshots"


def recordings_dir() -> Path:
    return _ensure_root() / "recordings"


def dtms_dir() -> Path:
    return _ensure_root() / "dtms"


def rois_dir() -> Path:
    return _ensure_root() / "rois"


def color(name: str) -> int:
    """Return a saved colour's PRIMARY sample as ``0xRRGGBB``.

    For multi-sample captures (gradient targets, boon procs), use
    :func:`colors` to get the whole stack. ``color`` always returns
    just the first/primary sample, which is the value the picker
    saved as ``rgb`` in the JSON.

    Raises :class:`KeyError` when nothing in the global library matches
    the slugified name.
    """
    data = color_with_meta(name)
    rgb = data.get("rgb")
    if not (isinstance(rgb, (list, tuple)) and len(rgb) == 3):
        raise ValueError(f"colour {name!r} has malformed rgb: {rgb!r}")
    r, g, b = (int(v) & 0xFF for v in rgb)
    return (r << 16) | (g << 8) | b


def colors(name: str) -> List[int]:
    """Return EVERY sample for a saved colour as a list of ``0xRRGGBB``.

    Returns ``[primary, *extras]`` — guaranteed non-empty (at minimum
    just the primary). Pair with
    :func:`ai.bot.find_any_color` so a bot can match anti-aliased /
    gradient / glow targets robustly:

        from ai.captures import colors
        from ai.bot import find_any_color

        SEREN_SAMPLES = colors("seren_spirit_halo")  # e.g. 5 samples
        m = find_any_color(SEREN_SAMPLES, tol=18, roi=POOL_ROI_WIDE)

    Backward compatible — if a JSON file only has the legacy ``rgb``
    field with no ``extra_rgbs``, the returned list is ``[primary]``.
    """
    data = color_with_meta(name)
    out: List[int] = [color(name)]    # primary, validated by color()
    extras = data.get("extra_rgbs") or []
    for entry in extras:
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3):
            continue
        try:
            r, g, b = (int(v) & 0xFF for v in entry)
        except Exception:
            continue
        out.append((r << 16) | (g << 8) | b)
    return out


def color_with_meta(name: str) -> Dict[str, Any]:
    """Same as :func:`color` but returns the full JSON payload — handy
    when a bot wants ``screen_xy``, ``captured_at``, or ``extra_rgbs``."""
    path = colors_dir() / f"{_slug(name)}.json"
    if not path.exists():
        raise KeyError(
            f"no global colour named {name!r} (looked in {path})"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def snapshot(name: str) -> Path:
    """Path to a saved global snapshot PNG. Raises :class:`KeyError` on miss."""
    path = snapshots_dir() / f"{_slug(name)}.png"
    if not path.exists():
        raise KeyError(
            f"no global snapshot named {name!r} (looked in {path})"
        )
    return path


def recording(name: str) -> Path:
    """Path to a saved global recording directory.

    Each recording dir contains ``frame_NNN.png`` files plus a
    ``meta.json``. Raises :class:`KeyError` on miss.
    """
    path = recordings_dir() / _slug(name)
    if not path.is_dir():
        raise KeyError(
            f"no global recording named {name!r} (looked in {path})"
        )
    return path


def dtm(name: str) -> Path:
    """Path to a saved global DTM template (the YAML).

    Pair with :func:`ai.bot.find_dtm` — the bot framework's
    ``dtm.find`` block accepts an absolute YAML path::

        from ai.captures import dtm
        from ai.bot import find_dtm

        BANK_CHEST = dtm("bank_chest_vip")    # → Path to .yaml

        @bot.rule(phase="banking")
        def click_chest():
            m = find_dtm(BANK_CHEST, roi=CHEST_ROI)
            ...

    Raises :class:`KeyError` on miss.
    """
    path = dtms_dir() / f"{_slug(name)}.yaml"
    if not path.exists():
        raise KeyError(
            f"no global DTM named {name!r} (looked in {path})"
        )
    return path


def roi(name: str) -> tuple:
    """Return a saved search ROI as ``(x, y, w, h)`` in physical pixels.

    Bots use this to scope their detection helpers (``find_color``,
    ``find_dtm``, ``is_animating``) to the right area of the screen
    without hardcoding tuples in the ``.py`` file::

        from ai.captures import roi

        POOL_ROI = roi("vip_pool_west")
        CHEST_ROI = roi("vip_bank_chest_search")

    Raises :class:`KeyError` when nothing in the global library
    matches the slugified name.
    """
    data = roi_with_meta(name)
    rect = data.get("rect")
    if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
        raise ValueError(
            f"ROI {name!r} has malformed rect: {rect!r}"
        )
    return tuple(int(v) for v in rect)


def roi_with_meta(name: str) -> Dict[str, Any]:
    """Same as :func:`roi` but returns the full JSON payload."""
    path = rois_dir() / f"{_slug(name)}.json"
    if not path.exists():
        raise KeyError(
            f"no global ROI named {name!r} (looked in {path})"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def list_global(kind: str = "colors") -> List[Path]:
    """Enumerate everything of one kind. ``kind`` ∈
    ``{"colors", "snapshots", "recordings", "dtms"}``. Returns absolute
    paths sorted alphabetically. The per-kind ``index.json`` registry
    is excluded so callers can iterate the result as actual capture
    payloads.
    """
    if kind == "colors":
        return sorted(
            p for p in colors_dir().glob("*.json")
            if p.name != "index.json"
        )
    if kind == "snapshots":
        return sorted(snapshots_dir().glob("*.png"))
    if kind == "recordings":
        return sorted(p for p in recordings_dir().iterdir() if p.is_dir())
    if kind == "dtms":
        return sorted(dtms_dir().glob("*.yaml"))
    if kind == "rois":
        return sorted(
            p for p in rois_dir().glob("*.json")
            if p.name != "index.json"
        )
    raise ValueError(
        f"unknown kind {kind!r}; expected one of "
        "'colors' | 'snapshots' | 'recordings' | 'dtms' | 'rois'"
    )


# ── Public write API (promote from a bundle to global) ──────────────


def promote_color(src: Path, *, name: Optional[str] = None) -> Path:
    """Copy a per-bundle colour JSON into the global colours directory.

    The destination filename is derived from (in order): an explicit
    ``name`` argument, the JSON's existing ``slug`` field, then the
    source filename stem. ``name`` (when given) becomes the new
    display name and rewrites the slug; otherwise the existing slug
    is preserved so the global filename matches what bots reference.
    """
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    data = json.loads(src.read_text(encoding="utf-8"))
    if name:
        slug = _slug(name)
        data["name"] = name
    else:
        slug = _slug(data.get("slug") or src.stem)
    data["slug"] = slug
    data["promoted_at"] = time.time()
    dst = colors_dir() / f"{slug}.json"
    dst.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _bump_index("colors", slug, data)
    return dst


def promote_snapshot(src: Path, *, name: Optional[str] = None) -> Path:
    """Copy a per-bundle snapshot PNG into the global snapshots directory."""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    slug = _slug(name or src.stem)
    dst = snapshots_dir() / f"{slug}.png"
    shutil.copyfile(src, dst)
    _bump_index("snapshots", slug, {
        "slug": slug,
        "name": name or slug,
        "promoted_at": time.time(),
    })
    return dst


def promote_recording(src_dir: Path, *, name: Optional[str] = None) -> Path:
    """Copy a per-bundle recording directory into the global recordings dir.

    Copies every file in ``src_dir`` (frame PNGs + meta.json). Doesn't
    recurse into subdirectories; recordings are flat.
    """
    src_dir = Path(src_dir)
    if not src_dir.is_dir():
        raise FileNotFoundError(src_dir)
    slug = _slug(name or src_dir.name)
    dst = recordings_dir() / slug
    dst.mkdir(parents=True, exist_ok=True)
    for child in src_dir.iterdir():
        if child.is_file():
            shutil.copyfile(child, dst / child.name)
    _bump_index("recordings", slug, {
        "slug": slug,
        "name": name or slug,
        "promoted_at": time.time(),
    })
    return dst


def promote_dtm(src_yaml: Path, *, name: Optional[str] = None) -> Path:
    """Copy a per-bundle DTM (YAML + paired PNG) into the global dtms dir.

    The PNG thumbnail is optional — if ``<src_yaml>.with_suffix(.png)``
    exists, it travels with the YAML so the global library card can
    render a preview.
    """
    src_yaml = Path(src_yaml)
    if not src_yaml.exists():
        raise FileNotFoundError(src_yaml)
    slug = _slug(name or src_yaml.stem)
    dst_yaml = dtms_dir() / f"{slug}.yaml"
    shutil.copyfile(src_yaml, dst_yaml)
    src_png = src_yaml.with_suffix(".png")
    if src_png.exists():
        shutil.copyfile(src_png, dtms_dir() / f"{slug}.png")
    _bump_index("dtms", slug, {
        "slug": slug,
        "name": name or slug,
        "promoted_at": time.time(),
    })
    return dst_yaml


def promote_roi(src: Path, *, name: Optional[str] = None) -> Path:
    """Copy a per-bundle ROI JSON into the global rois directory."""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)
    data = json.loads(src.read_text(encoding="utf-8"))
    if name:
        slug = _slug(name)
        data["name"] = name
    else:
        slug = _slug(data.get("slug") or src.stem)
    data["slug"] = slug
    data["promoted_at"] = time.time()
    dst = rois_dir() / f"{slug}.json"
    dst.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    _bump_index("rois", slug, data)
    return dst


def _bump_index(kind: str, slug: str, meta: Dict[str, Any]) -> None:
    """Update ``<kind>/index.json`` with a single entry per slug.

    Format mirrors the per-bundle index in
    ``ui/cards/ai_captures.AICapturesSection._append_index`` — a list
    of dicts, replacing any previous entry with the same slug so the
    index never grows duplicates.
    """
    base = _ensure_root() / kind
    index_path = base / "index.json"
    existing: List[Dict[str, Any]] = []
    if index_path.exists():
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                existing = payload
        except Exception:
            existing = []
    existing = [e for e in existing if e.get("slug") != slug]
    existing.append(meta)
    index_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── Delete (used by the library browser's trash affordance) ─────────


def delete_color(name: str) -> bool:
    """Remove a colour from the global library. Returns True iff it existed."""
    slug = _slug(name)
    path = colors_dir() / f"{slug}.json"
    if not path.exists():
        return False
    path.unlink()
    _drop_index("colors", slug)
    return True


def delete_snapshot(name: str) -> bool:
    slug = _slug(name)
    path = snapshots_dir() / f"{slug}.png"
    if not path.exists():
        return False
    path.unlink()
    _drop_index("snapshots", slug)
    return True


def delete_recording(name: str) -> bool:
    slug = _slug(name)
    path = recordings_dir() / slug
    if not path.is_dir():
        return False
    shutil.rmtree(path)
    _drop_index("recordings", slug)
    return True


def delete_dtm(name: str) -> bool:
    """Remove a global DTM (YAML + paired PNG if present)."""
    slug = _slug(name)
    path = dtms_dir() / f"{slug}.yaml"
    if not path.exists():
        return False
    path.unlink()
    paired = dtms_dir() / f"{slug}.png"
    if paired.exists():
        paired.unlink()
    _drop_index("dtms", slug)
    return True


def delete_roi(name: str) -> bool:
    slug = _slug(name)
    path = rois_dir() / f"{slug}.json"
    if not path.exists():
        return False
    path.unlink()
    _drop_index("rois", slug)
    return True


def _drop_index(kind: str, slug: str) -> None:
    index_path = _ensure_root() / kind / "index.json"
    if not index_path.exists():
        return
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(payload, list):
        return
    payload = [e for e in payload if e.get("slug") != slug]
    index_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
