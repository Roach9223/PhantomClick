"""BotBundle — per-bot folder layout + load/save.

Each user-authored bot lives under ``<root>/bots/<slug>/`` with its own
metadata, procedures, calibration, settings, and asset library. This
module is the single way to load/save that layout — the AI tab and
the runtime both go through ``BotBundle`` rather than reaching into
files directly.

Folder shape::

    bots/menaphos_vip_fishing/
    ├── bot.json                 # {slug, name, version, target_skill, …}
    ├── procedures.json          # the bot's procedures + interrupts
    ├── calibration.json         # ROIs scoped to this bot
    ├── settings.json            # tick rate, dry_run, watchdog thresholds
    ├── assets/
    │   ├── snapshots/           # per-asset PNGs + index.json
    │   ├── recordings/          # per-asset frame sequence dirs + meta.json
    │   ├── items/               # inventory icons (player capture > wiki)
    │   └── colors/              # eyedropped colour samples
    └── runs/                    # per-session telemetry (NOT loaded by Bundle)

The plan called for ``bot.toml`` but JSON is used for every file in
the bundle — same parser everywhere, no extra dependency, and editing
a JSON file by hand is no worse than TOML for this shape of data. If
TOML is ever needed it can be added on top without changing the
public surface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger


_log = get_logger("bot_bundle")


# ─────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────


_BUNDLE_VERSION = 1


_DEFAULT_BOT_META: Dict[str, Any] = {
    "slug": "",
    "name": "",
    "version": _BUNDLE_VERSION,
    "target_skill": "",          # "Fishing", "Woodcutting", …
    "description": "",
}

_DEFAULT_PROCEDURES: Dict[str, Any] = {
    # Empty bundle — until the user authors something. The compiler
    # treats this shape as "no rules to register" and surfaces an
    # error at Start, exactly like the v1 editor.
    "entry": "main",
    "procedures": {"main": []},
    "interrupts": [],
}

_DEFAULT_CALIBRATION: Dict[str, Any] = {
    "inventory_rect": None,
    "bars_rect": None,
    "minimap_rect": None,
    "orbs_max_fill": {},
}

_DEFAULT_SETTINGS: Dict[str, Any] = {
    "tick_rate_hz": 5.0,
    "dry_run": False,
    "auto_camera": False,
    "auto_stop_dry_ticks": 60,
    "watchdog_no_click_s": 600.0,
    # Per-bot realism override. None = inherit from the global cfg slider
    # (the typical case). A float in [0.0, 1.0] pins this bot to a fixed
    # realism level regardless of the global slider — useful when a bot's
    # cadence has been tuned for a specific level and shouldn't drift if
    # the user later moves the slider for a different bot.
    "realism": None,
}


# ─────────────────────────────────────────────────────────────────
# Slug helper
# ─────────────────────────────────────────────────────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Filesystem-safe lowercase slug. ``Menaphos VIP Fishing`` →
    ``menaphos_vip_fishing``. Same convention as the wiki client."""
    s = _SLUG_RE.sub("_", name.lower()).strip("_")
    return s or "unnamed_bot"


# ─────────────────────────────────────────────────────────────────
# BotBundle
# ─────────────────────────────────────────────────────────────────


@dataclass
class BotBundle:
    """One bot's entire on-disk state, loaded into memory."""

    slug: str
    root: Path                         # bots/<slug>/
    meta: Dict[str, Any] = field(default_factory=dict)
    procedures: Dict[str, Any] = field(default_factory=dict)
    calibration: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)

    # ── Public surface ──────────────────────────────────────────
    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.slug)

    @property
    def target_skill(self) -> str:
        return str(self.meta.get("target_skill") or "")

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    @property
    def snapshots_dir(self) -> Path:
        return self.assets_dir / "snapshots"

    @property
    def recordings_dir(self) -> Path:
        return self.assets_dir / "recordings"

    @property
    def items_dir(self) -> Path:
        return self.assets_dir / "items"

    @property
    def colors_dir(self) -> Path:
        return self.assets_dir / "colors"

    @property
    def dtm_dir(self) -> Path:
        return self.assets_dir / "dtm"

    @property
    def rois_dir(self) -> Path:
        return self.assets_dir / "rois"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def debug_dir(self) -> Path:
        # Per-bundle scratch space for debug screenshots / dumps.
        return self.root / "debug"

    def ensure_layout(self) -> None:
        """Create every standard subdirectory if it doesn't exist.

        Safe to call repeatedly. Touched on Bundle creation, on any
        capture write, and at run-start so a freshly-cloned bundle
        always has a valid skeleton.
        """
        for d in (
            self.root, self.assets_dir, self.snapshots_dir,
            self.recordings_dir, self.items_dir, self.colors_dir,
            self.dtm_dir, self.rois_dir, self.runs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    # ── Asset enumeration (cheap, no PNG load) ──────────────────
    def list_snapshots(self) -> List[Path]:
        return sorted(p for p in self.snapshots_dir.glob("*.png"))

    def list_recordings(self) -> List[Path]:
        # Each recording is a directory holding frame_NNN.png + meta.json.
        return sorted(p for p in self.recordings_dir.iterdir() if p.is_dir())

    def list_items(self) -> List[Path]:
        return sorted(p for p in self.items_dir.glob("*.png"))

    def list_colors(self) -> List[Path]:
        return sorted(p for p in self.colors_dir.glob("*.json"))

    def list_dtms(self) -> List[Path]:
        # Each DTM is a YAML; paired PNG (assets/dtm/<slug>.png) is for
        # thumbnails / debugging and lives next to the .yaml.
        return sorted(p for p in self.dtm_dir.glob("*.yaml"))

    def list_rois(self) -> List[Path]:
        # Each ROI is a single JSON file. Stored as physical-pixel
        # rects so bots can pass them directly to find_color(roi=...)
        # / find_dtm / is_animating without unit conversion.
        return sorted(
            p for p in self.rois_dir.glob("*.json")
            if p.name != "index.json"
        )

    def asset_path(self, name: str, kind: str) -> Optional[Path]:
        """Resolve an asset name (e.g. ``"bank_chest"``) to its path.

        ``kind`` is one of ``"snapshot" | "recording" | "item" | "color"``.
        Returns ``None`` if the asset doesn't exist in this bundle —
        callers can then fall back to the wiki cache.
        """
        slug = slugify(name)
        if kind == "snapshot":
            p = self.snapshots_dir / f"{slug}.png"
            return p if p.exists() else None
        if kind == "recording":
            p = self.recordings_dir / slug
            return p if p.is_dir() else None
        if kind == "item":
            p = self.items_dir / f"{slug}.png"
            return p if p.exists() else None
        if kind == "color":
            p = self.colors_dir / f"{slug}.json"
            return p if p.exists() else None
        return None

    # ── I/O ─────────────────────────────────────────────────────
    @classmethod
    def load(cls, root: Path) -> "BotBundle":
        """Load a bundle from a folder. Missing files use defaults
        — a fresh / partial bundle is loadable without errors so
        the editor can populate it incrementally.
        """
        root = Path(root).resolve()
        slug = root.name
        meta = _read_json(root / "bot.json", _DEFAULT_BOT_META)
        # Backfill slug from folder name if the JSON doesn't have one
        # (or doesn't agree with the folder).
        if not meta.get("slug"):
            meta["slug"] = slug
        if not meta.get("name"):
            meta["name"] = slug.replace("_", " ").title()

        procedures = _read_json(root / "procedures.json", _DEFAULT_PROCEDURES)
        calibration = _read_json(root / "calibration.json", _DEFAULT_CALIBRATION)
        settings = _read_json(root / "settings.json", _DEFAULT_SETTINGS)

        bundle = cls(
            slug=slug,
            root=root,
            meta=meta,
            procedures=procedures,
            calibration=calibration,
            settings=settings,
        )
        bundle.ensure_layout()
        return bundle

    @classmethod
    def create(
        cls, root_parent: Path, slug: str,
        *, name: Optional[str] = None, target_skill: str = "",
    ) -> "BotBundle":
        """Materialize a brand-new bundle on disk.

        ``root_parent`` is the ``bots/`` directory (parent of slug
        folders). Raises ``FileExistsError`` if the slug already
        exists — caller is responsible for picking a unique slug.
        """
        slug = slugify(slug)
        root = Path(root_parent) / slug
        if root.exists():
            raise FileExistsError(
                f"bundle already exists: {root}"
            )
        meta = dict(_DEFAULT_BOT_META)
        meta["slug"] = slug
        meta["name"] = name or slug.replace("_", " ").title()
        meta["target_skill"] = target_skill
        bundle = cls(
            slug=slug, root=root,
            meta=meta,
            procedures=dict(_DEFAULT_PROCEDURES),
            calibration=dict(_DEFAULT_CALIBRATION),
            settings=dict(_DEFAULT_SETTINGS),
        )
        bundle.ensure_layout()
        bundle.save()
        return bundle

    def save(self) -> None:
        """Write all four metadata JSONs to disk. Asset files are
        written separately via the capture / fetch helpers."""
        self.ensure_layout()
        _write_json(self.root / "bot.json", self.meta)
        _write_json(self.root / "procedures.json", self.procedures)
        _write_json(self.root / "calibration.json", self.calibration)
        _write_json(self.root / "settings.json", self.settings)

    def save_field(self, field_name: str) -> None:
        """Save just one of {meta, procedures, calibration, settings}
        without rewriting the others. Cheaper for hot-path edits."""
        if field_name == "meta":
            _write_json(self.root / "bot.json", self.meta)
        elif field_name == "procedures":
            _write_json(self.root / "procedures.json", self.procedures)
        elif field_name == "calibration":
            _write_json(self.root / "calibration.json", self.calibration)
        elif field_name == "settings":
            _write_json(self.root / "settings.json", self.settings)
        else:
            raise ValueError(f"unknown field {field_name!r}")


# ─────────────────────────────────────────────────────────────────
# Discovery helpers
# ─────────────────────────────────────────────────────────────────


def bundles_root(config_dir: Path) -> Path:
    """``<config_dir>/bots/`` — created on first access."""
    p = Path(config_dir) / "bots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def list_bundles(config_dir: Path) -> List[BotBundle]:
    """Return every bundle in ``<config_dir>/bots/``, sorted by name.

    Folders without a ``bot.json`` are tolerated — they load with
    default metadata so the user can always see what's on disk.
    Folders without any of the four files are still included as long
    as they exist; this lets the editor recover broken bundles.
    """
    root = bundles_root(config_dir)
    out: List[BotBundle] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            out.append(BotBundle.load(child))
        except Exception as e:
            _log.warning("failed to load bundle at %s: %s", child, e)
    out.sort(key=lambda b: b.name.lower())
    return out


def find_bundle(config_dir: Path, slug: str) -> Optional[BotBundle]:
    """Look up a bundle by slug. Returns ``None`` if it doesn't exist."""
    root = bundles_root(config_dir) / slug
    if not root.is_dir():
        return None
    try:
        return BotBundle.load(root)
    except Exception as e:
        _log.warning("failed to load bundle %s: %s", slug, e)
        return None


# ─────────────────────────────────────────────────────────────────
# JSON I/O — atomic writes so a crash mid-save can't corrupt
# ─────────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        _log.warning("corrupt %s — using defaults (%s)", path, e)
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    # Backfill any missing keys from defaults so older bundles still
    # work after a schema bump.
    merged = dict(default)
    merged.update(data)
    return merged


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomic JSON write — write to a temp file, then rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
