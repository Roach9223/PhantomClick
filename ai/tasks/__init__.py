"""Task layer — the primary object model in the Studio.

A Task bundles *intent* (name, goal, location, signals) with
*implementation* (one ``.rvscript`` graph, either inline or referenced)
and *runtime state* (idle/running/paused/failed + phase + counters).

The graph editor, block library, and node graph are now a *tab inside*
the active Task's workspace, not the primary surface.
"""

from __future__ import annotations

from .model import Task, TaskHealth, TaskPhase, TaskState
from .store import TaskStore

__all__ = ["Task", "TaskHealth", "TaskPhase", "TaskState", "TaskStore"]
