"""``StatsPageBody`` — per-session counters as form rows.

The 2026 redesign trades the prior 3+2 stat-tile grid for a
:class:`SettingsGroup` of rows. Each metric becomes one row with the
metric name on the left and a big mono value chip on the right. Same
visual punch (mono 18 px), better cohesion with the rest of the
form-style pages.

:meth:`tick` runs every frame from the App's ``_ticking_cards`` loop.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from modules.stats import format_elapsed

from .. import theme as t
from ..format import fmt_count, fmt_delay, fmt_position, fmt_rate
from ..widgets.group_header import GroupHeader
from ..widgets.settings_group import SettingsGroup
from ..widgets.settings_row import SettingsRow


_METRICS = (
    ("total", "Total clicks",
     "Clicks fired in the current session.", "0"),
    ("cpm", "Clicks per minute",
     "Derived from the rolling average interval.", "—"),
    ("elapsed", "Elapsed",
     "Time since the most recent Start press.", "00:00:00"),
    ("avg", "Average interval",
     "Rolling 60-click average — reflects fatigue + idle wander, "
     "not just your timing range.", "—"),
    ("last", "Last click position",
     "Screen coordinates of the most recent click.", "—"),
)


class StatsPageBody(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(GroupHeader("Session"))

        # Mono font set explicitly: QSS attribute selectors don't always win
        # over Qt's inherited QFont when the label is parented after the
        # property is set, so we lock font-family + size on the QLabel itself.
        stat_font = QFont(t.FONT_MONO.split(",")[0].strip())
        stat_font.setPixelSize(t.SIZE_STAT_VALUE)
        stat_font.setWeight(QFont.Medium)

        self._values: dict[str, QLabel] = {}
        group = SettingsGroup()
        for key, title, desc, initial in _METRICS:
            row = SettingsRow(title, desc=desc)
            value = QLabel(initial)
            value.setProperty("role", "stat-value")
            value.setFont(stat_font)
            value.setMinimumWidth(120)
            self._values[key] = value
            row.set_control(value)
            group.add_row(row)
        outer.addWidget(group)

        outer.addSpacing(t.SP_MD)

        footer = QLabel(
            "Counters reset on every Start press. The topbar pill shows "
            "the live state + countdown from any page."
        )
        footer.setProperty("role", "footer-hint")
        footer.setWordWrap(True)
        outer.addWidget(footer)

    def tick(self) -> None:
        snap = self.app.stats.snapshot()
        self._values["total"].setText(fmt_count(snap["total"]))
        self._values["elapsed"].setText(format_elapsed(snap["elapsed"]))
        avg = snap["avg_interval"]
        self._values["avg"].setText(fmt_delay(avg) if avg > 0 else "—")
        cpm = snap["cpm"]
        self._values["cpm"].setText(fmt_rate(cpm, "CPM") if cpm > 0 else "—")
        lp = snap["last_pos"]
        self._values["last"].setText(fmt_position(*lp) if lp else "—")


# Back-compat alias: ui/app.py still references StatsCard.
StatsCard = StatsPageBody
