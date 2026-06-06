"""The :class:`Bot` class — container + ``@bot.rule`` decorator.

Every ``.py`` bot script looks like::

    bot = Bot(name="Draynor Willows")

    @bot.rule(phase="chopping")
    def chop():
        ...

    if __name__ == "__main__":
        bot.run()

:class:`Bot` only stores metadata + rules — it doesn't run them.
Execution happens via :class:`rs3vision_studio.bot.runner.BotRunner`
which loops ticks, evaluates rules in order, and emits Qt signals the
Studio consumes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class Rule:
    """Metadata for one decorated rule function."""

    name: str
    func: Callable[[], Any]
    phase: str = ""
    enabled: bool = True


class Bot:
    """Top-level container in a bot script."""

    def __init__(
        self,
        name: str,
        *,
        slug: Optional[str] = None,
        monitor: Optional[int] = None,
        tick_rate_hz: float = 5.0,
        dry_run: bool = True,
        # Humanizer overrides (merged into the Studio default at run time).
        fatigue_intensity: Optional[float] = None,
        break_min_clicks: Optional[int] = None,
        break_max_clicks: Optional[int] = None,
        break_min_duration_s: Optional[float] = None,
        break_max_duration_s: Optional[float] = None,
        require_foreground_window: bool = False,
        target_window_exe: str = "rs2client.exe",
        # AFK reliability knobs.
        auto_stop_dry_ticks: int = 60,
        watchdog_no_click_s: float = 600.0,
        # Auto-camera — when detection misses for ``auto_camera_dry_ticks``
        # consecutive ticks, the runner issues a camera rotation to try
        # unsticking the scene. Gives up after ``auto_camera_max_bursts``
        # rotations with no match; then the AFK watchdog takes over.
        auto_camera: bool = False,
        auto_camera_dry_ticks: int = 5,
        auto_camera_step_deg: float = 45.0,
        auto_camera_max_bursts: int = 4,
    ) -> None:
        self.name = str(name)
        self.slug = slug or _default_slug(self.name)
        self.monitor = monitor
        self.tick_rate_hz = float(tick_rate_hz)
        self.dry_run = bool(dry_run)
        self.rules: List[Rule] = []

        self.humanizer_overrides: Dict[str, Any] = {}
        for k, v in {
            "fatigue_intensity": fatigue_intensity,
            "break_min_clicks": break_min_clicks,
            "break_max_clicks": break_max_clicks,
            "break_min_duration_s": break_min_duration_s,
            "break_max_duration_s": break_max_duration_s,
            "require_foreground_window": require_foreground_window,
            "target_window_exe": target_window_exe,
        }.items():
            if v is not None and not (isinstance(v, bool) and v is False and k == "require_foreground_window"):
                self.humanizer_overrides[k] = v

        self.auto_stop_dry_ticks = int(auto_stop_dry_ticks)
        self.watchdog_no_click_s = float(watchdog_no_click_s)
        self.auto_camera = bool(auto_camera)
        self.auto_camera_dry_ticks = max(1, int(auto_camera_dry_ticks))
        self.auto_camera_step_deg = float(auto_camera_step_deg)
        self.auto_camera_max_bursts = max(1, int(auto_camera_max_bursts))

    # ────────────────────────────────────────────────────────────
    # Decorator
    # ────────────────────────────────────────────────────────────
    def rule(
        self,
        _func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        phase: str = "",
        enabled: bool = True,
    ):
        """Register a rule function.

        Two forms::

            @bot.rule                         # uses function name
            def chop(): ...

            @bot.rule(phase="banking")        # with kwargs
            def bank(): ...
        """

        def _wrap(func: Callable) -> Callable:
            self.rules.append(Rule(
                name=name or func.__name__,
                func=func,
                phase=phase,
                enabled=enabled,
            ))
            return func

        if _func is not None and callable(_func):
            return _wrap(_func)
        return _wrap

    # ────────────────────────────────────────────────────────────
    # Standalone runner — for ``python my_bot.py``
    # ────────────────────────────────────────────────────────────
    def run(self) -> None:
        """Run the bot outside the Studio (no Qt, simple console loop).

        This path is deliberately minimal — no live graph view, no MCP.
        For full instrumentation, load the bot via the Studio.
        """
        from .runner import standalone_run
        standalone_run(self)


def _default_slug(name: str) -> str:
    slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower())
    return slug.strip("_") or "bot"
