"""Load + save ``*.task.yaml`` files, discover tasks, track recents.

Two discovery roots:

1. **Library** — ``rs3vision_studio/tasks/library/`` (ships with the
   app; read-only-ish; user can copy from here to customise).
2. **User** — ``rs3vision-studio/tasks/`` (repo-local, gitignored) and
   ``~/.rs3vision/tasks/`` (per-user). Writeable.

Recents are kept via :class:`PySide6.QtCore.QSettings` so they survive
reinstalls without littering disk with dotfiles.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .model import (
    TASK_SCHEMA_VERSION,
    Task,
    TaskLocation,
)


_STUDIO_PKG_ROOT = Path(__file__).resolve().parent.parent           # …/rs3vision_studio
_LIBRARY_DIR = _STUDIO_PKG_ROOT / "tasks" / "library"
_REPO_ROOT = _STUDIO_PKG_ROOT.parent                                # …/rs3vision-studio
_USER_REPO_DIR = _REPO_ROOT / "tasks"                               # gitignored
_USER_HOME_DIR = Path.home() / ".rs3vision" / "tasks"

SETTINGS_ORG = "rs3vision"
SETTINGS_APP = "Studio"
RECENT_KEY = "tasks/recent_slugs"
LAST_ACTIVE_KEY = "tasks/last_active_slug"
MAX_RECENTS = 8


# ─────────────────────────────────────────────────────────────────
# Load / save
# ─────────────────────────────────────────────────────────────────


def load_task(path: Path) -> Task:
    """Parse a ``*.task.yaml`` into a :class:`Task`."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    version = data.get("task")
    if version != TASK_SCHEMA_VERSION:
        raise ValueError(
            f"{path}: unsupported task schema version {version!r} "
            f"(expected {TASK_SCHEMA_VERSION})"
        )

    slug = str(data.get("slug") or path.stem)
    name = str(data.get("name") or slug.replace("_", " ").title())

    loc_raw = data.get("location") or {}
    location = TaskLocation(
        region=str(loc_raw.get("region", "")),
        coords=list(loc_raw["coords"]) if isinstance(loc_raw.get("coords"), (list, tuple)) else None,
        notes=str(loc_raw.get("notes", "")),
    )

    script_raw = data.get("script") or {}
    if isinstance(script_raw, dict):
        script_inline = script_raw.get("inline")
        script_ref = script_raw.get("ref")
    else:
        script_inline = None
        script_ref = None

    # Python-bot counterpart to ``script``. Shape:
    # ``bot: { ref: "path/to/bot_script.py" }``.
    bot_raw = data.get("bot") or {}
    if not isinstance(bot_raw, dict):
        bot_raw = {}
    bot_script_ref = bot_raw.get("ref")

    task = Task(
        slug=slug,
        name=name,
        goal=str(data.get("goal", "")),
        location=location,
        phases=list(data.get("phases") or []),
        success_signals=list(data.get("success_signals") or []),
        failure_signals=list(data.get("failure_signals") or []),
        params=dict(data.get("params") or {}),
        script_inline=script_inline if isinstance(script_inline, dict) else None,
        script_ref=str(script_ref) if script_ref else None,
        bot_script_ref=str(bot_script_ref) if bot_script_ref else None,
        author=str(data.get("author", "")),
        created=str(data.get("created", "")),
        tags=list(data.get("tags") or []),
        source_path=path,
        is_library=_is_in_library(path),
    )
    return task


def save_task(task: Task, path: Optional[Path] = None) -> Path:
    """Write ``task`` to ``path`` (or ``task.source_path``).

    Always writes schema v1. Library tasks can be saved to a user
    directory; the ``is_library`` flag is *not* persisted.
    """
    if path is None:
        path = task.source_path
    if path is None:
        raise ValueError("save_task needs an explicit path for tasks with no source")

    payload: Dict[str, Any] = {
        "task": TASK_SCHEMA_VERSION,
        "slug": task.slug,
        "name": task.name,
    }
    if task.goal:
        payload["goal"] = task.goal
    if task.location.region or task.location.coords or task.location.notes:
        loc: Dict[str, Any] = {}
        if task.location.region:
            loc["region"] = task.location.region
        if task.location.coords:
            loc["coords"] = list(task.location.coords)
        if task.location.notes:
            loc["notes"] = task.location.notes
        payload["location"] = loc
    if task.phases:
        payload["phases"] = list(task.phases)
    if task.success_signals:
        payload["success_signals"] = list(task.success_signals)
    if task.failure_signals:
        payload["failure_signals"] = list(task.failure_signals)
    if task.params:
        payload["params"] = dict(task.params)

    script_block: Dict[str, Any] = {}
    if task.script_inline is not None:
        script_block["inline"] = task.script_inline
    if task.script_ref is not None:
        script_block["ref"] = task.script_ref
    if script_block:
        payload["script"] = script_block

    if task.bot_script_ref is not None:
        payload["bot"] = {"ref": task.bot_script_ref}

    if task.author:
        payload["author"] = task.author
    if task.created:
        payload["created"] = task.created
    else:
        payload["created"] = datetime.date.today().isoformat()
    if task.tags:
        payload["tags"] = list(task.tags)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    task.source_path = path
    task.is_library = _is_in_library(path)
    return path


# ─────────────────────────────────────────────────────────────────
# Directory discovery
# ─────────────────────────────────────────────────────────────────


def library_dir() -> Path:
    return _LIBRARY_DIR


def user_dirs() -> List[Path]:
    """User-writeable task directories, in search order."""
    return [_USER_REPO_DIR, _USER_HOME_DIR]


def default_user_dir() -> Path:
    """Where ``save_task`` drops new user tasks by default."""
    _USER_REPO_DIR.mkdir(parents=True, exist_ok=True)
    return _USER_REPO_DIR


def _is_in_library(path: Path) -> bool:
    try:
        path.resolve().relative_to(_LIBRARY_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False


# ─────────────────────────────────────────────────────────────────
# TaskStore — the object the app uses
# ─────────────────────────────────────────────────────────────────


class TaskStore:
    """In-memory catalogue of available tasks.

    Scans the library + user directories on construction (and on
    explicit :meth:`refresh`). Raises nothing on per-file parse errors —
    they're collected in :attr:`errors` and surfaced to the log.
    """

    def __init__(self) -> None:
        self.library: List[Task] = []
        self.user: List[Task] = []
        self.errors: List[str] = []  # "path: reason" strings
        self.refresh()

    # ── discovery ─────────────────────────────────────────────
    def refresh(self) -> None:
        self.library = []
        self.user = []
        self.errors = []
        self._scan(_LIBRARY_DIR, into=self.library)
        for d in user_dirs():
            self._scan(d, into=self.user)

    def _scan(self, root: Path, *, into: List[Task]) -> None:
        if not root.exists() or not root.is_dir():
            return
        for path in sorted(root.glob("*.task.yaml")):
            try:
                task = load_task(path)
            except Exception as e:
                self.errors.append(f"{path}: {type(e).__name__}: {e}")
                continue
            into.append(task)

    # ── queries ───────────────────────────────────────────────
    def all(self) -> List[Task]:
        """All tasks, library first then user."""
        return [*self.library, *self.user]

    def by_slug(self, slug: str) -> Optional[Task]:
        for t in self.all():
            if t.slug == slug:
                return t
        return None

    def summaries(self) -> List[Dict[str, Any]]:
        """Compact dicts for MCP ``list_tasks`` + UI grids."""
        out = []
        for t in self.all():
            out.append({
                "slug": t.slug,
                "name": t.name,
                "goal": t.goal,
                "is_library": t.is_library,
                "source": str(t.source_path) if t.source_path else None,
                "tags": list(t.tags),
            })
        return out


# ─────────────────────────────────────────────────────────────────
# Recent-tasks MRU (via QSettings — no disk footprint we manage)
# ─────────────────────────────────────────────────────────────────


def _qsettings():
    from PySide6.QtCore import QSettings
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def get_recent_slugs() -> List[str]:
    raw = _qsettings().value(RECENT_KEY, "")
    if not raw:
        return []
    return [s for s in str(raw).split("|") if s]


def push_recent_slug(slug: str) -> None:
    if not slug:
        return
    slugs = [slug] + [s for s in get_recent_slugs() if s != slug]
    slugs = slugs[:MAX_RECENTS]
    _qsettings().setValue(RECENT_KEY, "|".join(slugs))


def get_last_active_slug() -> str:
    return str(_qsettings().value(LAST_ACTIVE_KEY, ""))


def set_last_active_slug(slug: str) -> None:
    _qsettings().setValue(LAST_ACTIVE_KEY, slug or "")


# ─────────────────────────────────────────────────────────────────
# Script resolution — turn a Task's script field into an rvscript dict
# ─────────────────────────────────────────────────────────────────


def resolve_script_dict(task: Task) -> Dict[str, Any]:
    """Return the Task's underlying ``.rvscript`` payload as a dict.

    Retained for back-compat. :func:`resolve_implementation` is the
    newer entry point that handles both script and playbook tasks.
    """
    from ..graph.format import load_file  # late import — heavy deps

    if task.script_inline:
        return dict(task.script_inline)

    if task.script_ref:
        ref = Path(task.script_ref)
        candidates = [ref]
        if task.source_path is not None:
            candidates.append(task.source_path.parent / task.script_ref)
        candidates.append(_REPO_ROOT / task.script_ref)
        candidates.append(_STUDIO_PKG_ROOT / task.script_ref)
        for cand in candidates:
            if cand.is_file():
                return load_file(cand)
        raise FileNotFoundError(
            f"task {task.slug!r} script_ref {task.script_ref!r} not found "
            f"(tried: {', '.join(str(c) for c in candidates)})"
        )

    raise ValueError(f"task {task.slug!r} has no script (inline nor ref)")


def resolve_implementation(task: Task):
    """Return the Task's implementation.

    Return shape:
    - ``("script", dict)`` for graph-backed tasks.
    - ``("bot", Bot)`` for Python-DSL tasks (imports the script module
      and returns its top-level ``bot`` object).
    """
    kind = task.implementation_kind()
    if kind == "script":
        return "script", resolve_script_dict(task)
    if kind == "bot":
        from ..bot import load_bot_from_path  # late import
        if not task.bot_script_ref:
            raise ValueError(f"task {task.slug!r} has no bot_script_ref")
        ref = Path(task.bot_script_ref)
        candidates = [ref]
        if task.source_path is not None:
            candidates.append(task.source_path.parent / task.bot_script_ref)
        candidates.append(_REPO_ROOT / task.bot_script_ref)
        candidates.append(_STUDIO_PKG_ROOT / task.bot_script_ref)
        for cand in candidates:
            if cand.is_file():
                return "bot", load_bot_from_path(cand)
        raise FileNotFoundError(
            f"task {task.slug!r} bot_script_ref {task.bot_script_ref!r} not found "
            f"(tried: {', '.join(str(c) for c in candidates)})"
        )
    raise ValueError(f"task {task.slug!r} has no implementation (script nor bot)")
