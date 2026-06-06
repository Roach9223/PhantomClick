"""Task dataclass + supporting types.

A :class:`Task` is the Studio's primary object. It *owns* a
``.rvscript`` graph (either inline or by reference), declares a
human-readable intent (name, goal, location), lists the phases it
expects to progress through, and carries a :class:`TaskHealth` snapshot
when running.

Tasks serialise to ``*.task.yaml`` via :mod:`rs3vision_studio.tasks.store`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


TASK_SCHEMA_VERSION = 1


class TaskState(str, Enum):
    """Run-state of the task inside the Studio."""

    IDLE = "idle"          # loaded but not running
    RUNNING = "running"    # runtime walking the graph
    PAUSED = "paused"      # reserved for future pause-support
    FAILED = "failed"      # stopped with an exception
    STOPPED = "stopped"    # stopped cleanly (user or flow.stop)


@dataclass
class TaskPhase:
    """Where the task thinks it is inside its own workflow.

    ``name`` is declared by the Task's ``phases`` list; runtime code
    can tag blocks with a ``phase=`` hint and the phase bubbles up as
    blocks execute.
    """

    name: str = "idle"
    entered_at: float = 0.0   # monotonic seconds
    history: List[str] = field(default_factory=list)  # recent phase names (capped)


@dataclass
class TaskHealth:
    """Live counters + health signal emitted by :class:`TaskRuntime`.

    All fields are snapshot-readable from the Qt main thread; the
    runtime mutates them on signal dispatch, not directly from the
    worker thread.
    """

    ticks: int = 0
    clicks: int = 0
    detections: int = 0
    failures: int = 0
    fps: float = 0.0
    last_error: str = ""
    last_detection_ts: float = 0.0
    healthy: bool = True


@dataclass
class TaskLocation:
    """Where this task takes place, for user orientation."""

    region: str = ""                       # free-text, e.g. "Draynor Village"
    coords: Optional[List[int]] = None     # [x, y] world tile, optional
    notes: str = ""


@dataclass
class Task:
    """A Task definition — the user-editable, persisted form.

    Runtime state (``state``, ``phase``, ``health``) is *not* persisted;
    it lives on the in-memory Task and is reset on load.
    """

    # ── persisted intent ──────────────────────────────────────────
    slug: str                              # stable id — matches filename
    name: str                              # human label
    goal: str = ""                         # one-line goal text
    location: TaskLocation = field(default_factory=TaskLocation)
    phases: List[str] = field(default_factory=list)
    success_signals: List[str] = field(default_factory=list)
    failure_signals: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)

    # ── persisted implementation ──────────────────────────────────
    # A Task is either a graph-backed (.rvscript) or Python-bot-backed
    # (.py) automation. Load-time validation enforces mutual exclusion.
    #
    # ``script_inline``     → serialised .rvscript dict (graph).
    # ``script_ref``        → path to an .rvscript file.
    # ``bot_script_ref``    → path to a Python bot script (module form);
    #                         the script defines a top-level ``bot``
    #                         object from ``rs3vision_studio.bot.Bot``.
    script_inline: Optional[Dict[str, Any]] = None
    script_ref: Optional[str] = None
    bot_script_ref: Optional[str] = None

    # ── persisted metadata ────────────────────────────────────────
    author: str = ""
    created: str = ""                      # ISO date, loosely
    tags: List[str] = field(default_factory=list)

    # ── non-persisted provenance ──────────────────────────────────
    # Absolute path the task was loaded from, if any.
    source_path: Optional[Path] = None
    is_library: bool = False               # came from tasks/library/

    # ── non-persisted runtime state ───────────────────────────────
    state: TaskState = TaskState.IDLE
    phase: TaskPhase = field(default_factory=TaskPhase)
    health: TaskHealth = field(default_factory=TaskHealth)
    started_at: float = 0.0                # monotonic seconds

    # ────────────────────────────────────────────────────────────
    # Helpers
    # ────────────────────────────────────────────────────────────
    def has_inline_script(self) -> bool:
        return isinstance(self.script_inline, dict) and bool(self.script_inline)

    def has_bot_script(self) -> bool:
        return bool(self.bot_script_ref)

    def implementation_kind(self) -> str:
        """One of ``"bot"`` / ``"script"`` / ``"none"``.

        A freshly-minted blank Task has no implementation yet. A Task
        with both slots populated counts as ``"bot"`` — the Python
        path is the newer system and takes precedence.
        """
        if self.bot_script_ref:
            return "bot"
        if self.script_inline or self.script_ref:
            return "script"
        return "none"

    def has_conflicting_implementations(self) -> bool:
        has_script = bool(self.script_inline or self.script_ref)
        has_bot = bool(self.bot_script_ref)
        return has_script and has_bot

    def reset_runtime_state(self) -> None:
        """Called before (re-)loading or on task switch — wipe counters."""
        self.state = TaskState.IDLE
        self.phase = TaskPhase()
        self.health = TaskHealth()
        self.started_at = 0.0
