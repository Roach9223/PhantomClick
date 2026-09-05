"""Help page, full-width documentation for new users.

Single scrollable column with sections covering: what the app is, how
each mode works, every step kind, hover zones, the realism dial,
hotkeys, and a small FAQ. Content lives here in code (not Markdown) so
it shares the app's typography and color tokens.

Sections are built from a tiny set of helpers (heading / paragraph /
bullet / kv) so the page reads more like prose than UI code.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

from .. import theme as t


_DOC_MAX_W = 820


class HelpPage(QWidget):
    def __init__(self, app, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app = app

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)

        # Centered max-width column for prose readability.
        inner = QWidget()
        inner_h = QHBoxLayout(inner)
        inner_h.setContentsMargins(t.SP_LG, t.SP_LG, t.SP_LG, t.SP_LG)
        inner_h.setSpacing(0)
        inner_h.addStretch(1)

        column = QWidget()
        column.setMaximumWidth(_DOC_MAX_W)
        col_layout = QVBoxLayout(column)
        col_layout.setContentsMargins(0, 0, 0, 0)
        col_layout.setSpacing(t.SP_MD)

        self._cl = col_layout
        self._build_sections()
        col_layout.addStretch(1)

        inner_h.addWidget(column, 0, Qt.AlignTop)
        inner_h.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll)

    def rebuild(self) -> None:
        """Re-render after a hotkey rebind so the key names stay current."""
        while self._cl.count():
            item = self._cl.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._build_sections()
        self._cl.addStretch(1)

    # -- Builders --------------------------------------------------------

    def _key(self, cfg_key: str) -> str:
        from modules.hotkey_manager import name_to_display
        from ui.config_io import DEFAULTS
        return name_to_display(str(self.app.cfg.get(cfg_key, DEFAULTS.get(cfg_key, ""))))

    def _build_sections(self) -> None:
        start = self._key("hotkey_start")
        stop = self._key("hotkey_stop")
        pause = self._key("hotkey_pause")
        capture = self._key("hotkey_capture")

        self._title("Help & Reference")
        self._lead(
            "PhantomClick is a human-like auto-clicker. The cursor "
            "physically moves along curved paths, dwells, jitters, and "
            "occasionally takes breaks. The goal is to look like a "
            "person, not a script. Everything runs locally. The only "
            "network features are the opt-in Monitor server on your own "
            "LAN and the opt-in wiki icon fetch, both off by default."
        )

        self._h2("Quick start: Click mode")
        self._p(
            "Use this when one button keeps appearing in the same "
            "place on screen."
        )
        self._ol([
            "Open the Click tab from the rail.",
            "Pick a shape (Rect / Circle / Custom) and press "
            "“Draw click zone.” Drag on screen to define it.",
            "Set the timing range. The engine waits a random duration "
            "between Min and Max before each click. Try the Fast / "
            "Medium / Slow presets.",
            f"Press START (or {start}). Pre-start delay gives you time to "
            "alt-tab into the target window before the first click.",
            f"Press STOP ({stop}) or Esc to halt.",
        ])

        self._h2("Sequence: Record mode")
        self._p(
            "Use this for routines: click a button, wait, follow a "
            "moving target, click again, then loop. The list runs "
            "top to bottom and wraps back to the start."
        )

        self._h2("Step kinds")
        self._kv("Click",
                 "Click in a fixed zone N times before advancing.")
        self._kv("Track",
                 "Follow a captured target via OpenCV template "
                 "matching. Use “+ Add view” for extra captures of the "
                 "same target (rotation, camera angle); the best match "
                 "wins each frame.")
        self._kv("Color",
                 "Eyedropper picks a target color; click several shades "
                 "to accept all of them. The engine clicks any matching "
                 "pixel on the monitor you picked from. “Set click area” "
                 "restricts matches to a drawn zone, which matters when "
                 "the HUD shares the color.")
        self._kv("Key",
                 "Press a key or combo (F1, Ctrl+Shift+Z) through the "
                 "input backend chosen under Settings. No cursor motion.")
        self._kv("Pause",
                 "Wait Min to Max seconds. Cursor still drifts.")
        self._kv("Loop",
                 "Jump execution back to an earlier step. Forever, "
                 "or N more times before continuing past.")

        self._h2("AI mode")
        self._p(
            "Rule-based RuneScape bots. Pick a bot (a bundle you built "
            "in the editor, or one shipped in the library), then START. "
            "Each tick the runner evaluates every rule in priority order "
            "and dispatches the first action through the same humanizer "
            "and key backend the other modes use. START, STOP, the status "
            "pill and Esc behave exactly as they do for Click and Record."
        )
        self._kv(f"{pause}", "Pause or resume the running bot. Click and "
                             "Record ignore this key.")
        self._kv(f"{capture}", "Freeze the screen and drag a rectangle to "
                               "save a snapshot into the active bundle's "
                               "library (needs an active bundle).")
        self._kv("Dry run", "Evaluate rules and log actions without "
                            "moving the mouse. Good for checking detection.")

        self._h2("Key timers")
        self._p(
            "Passive keypresses on their own clock, for things like "
            "“press Z every 6 minutes.” They run alongside whatever "
            "sequence is active, never move the cursor, and stop when "
            "the engine stops. A start is refused when a timer or Key "
            "step needs a key backend that isn't available."
        )

        self._h2("Monitor")
        self._p(
            "Opt-in LAN page for your phone: a live MJPEG view of the "
            "screen plus a status panel. A second toggle allows remote "
            "Start / Stop / Close-RuneScape buttons. Access is by a random "
            "URL token; regenerate it to invalidate old links. Anyone on "
            "your Wi-Fi with the URL can watch (and control, if enabled), "
            "so keep both off when you don't need them."
        )

        self._h2("Settings")
        self._kv("Target monitor", "Which screen ambient features (drift, "
                                   "wander, watchdog corners) treat as the "
                                   "screen. Auto follows your zone.")
        self._kv("Key input", "SendInput for most apps. Serial HID (an "
                              "Arduino running PhantomHID) is the only "
                              "path RuneScape NXT accepts.")
        self._kv("Wiki fetch", "Lets the AI item library download icons "
                               "from runescape.wiki. Off by default; no "
                               "HTTP requests leave the machine until "
                               "you turn it on.")
        self._kv("Mouse trace", "Records every cursor write to a JSONL "
                                "file for diagnosing movement issues.")

        self._h2("Hover zones")
        self._p(
            "Extra regions where the cursor occasionally drifts "
            "without clicking. Adds the small in-between motion humans "
            "make. Open the Hover tab to add zones."
        )

        self._h2("Realism dial")
        self._p(
            "One slider on the Behavior tab drives every humanization "
            "behavior: idle wander, fatigue, breaks, overshoots, "
            "anti-cluster, hover frequency. Most users never need to "
            "open Advanced. Moving the dial overwrites Advanced values; "
            "set the dial first, then override individual settings if "
            "you want fine control."
        )

        self._h2("Hotkeys")
        self._kv("Start", start)
        self._kv("Stop", stop)
        self._kv("Pause / resume bot", f"{pause} (AI mode only)")
        self._kv("Capture frame", f"{capture} (AI mode, needs an active bundle)")
        self._kv("Emergency stop", "Esc (always works, can't be rebound)")
        self._kv("Command palette", "Ctrl+K, fuzzy-search every action")
        self._kv("Switch tab", "Ctrl+1 Click / Ctrl+2 Record / Ctrl+3 AI / "
                               "Ctrl+4 Monitor / Ctrl+5 Settings")
        self._kv("Draw click zone", "Ctrl+D")
        self._kv("Toggle overlays", "Ctrl+H")
        self._kv("Help", "F1")
        self._p("Start, Stop, Pause and Capture are rebindable on the "
                "Hotkeys tab. Esc stays fixed.")

        self._h2("Tips")
        self._ul([
            "Pre-start delay (Behavior tab) lets you alt-tab into the "
            "target window after pressing Start.",
            "Slamming the cursor to any screen corner emergency-stops "
            "the engine within ~50 ms.",
            "Drift-across-whole-screen (on the Click tab) lets the "
            "idle wander roam the full monitor. Clicks still come "
            "from the zone you drew.",
            "Use the command palette (Ctrl+K) to set a timing preset, "
            "draw a zone, or jump to a tab without touching the rail.",
        ])

        self._h2("FAQ")
        self._faq(
            "Why isn't it clicking?",
            "Most often: the click zone isn't set (Click mode) or no "
            "step has a target yet (Record mode). The status pill in "
            "the topbar will say what's missing."
        )
        self._faq(
            "Why does it pause for several seconds at random?",
            "Break bursts, by design. Realism includes scheduled "
            "multi-second pauses every 40-70 clicks to simulate "
            "looking away. Disable in Behavior · Advanced."
        )
        self._faq(
            "Can it click in a fullscreen game?",
            "Yes. Hotkeys are global. Overlays are click-through. "
            "The cursor physically moves so the OS treats clicks as "
            "real input."
        )
        self._faq(
            "What about multiple monitors?",
            "Zones, captures and color picks work on any monitor, "
            "including mixed DPI. Ambient drift is scoped to the "
            "Settings target monitor (auto follows your zone). AI mode "
            "pins to one monitor index."
        )

    # -- Helpers ---------------------------------------------------------

    def _title(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; "
            f"font-size: 24px; font-weight: 700; "
            f"letter-spacing: 0.5px; padding-bottom: {t.SP_SM}px;"
        )
        self._cl.addWidget(lbl)

    def _lead(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; font-size: 15px; "
            f"line-height: 1.6; padding-bottom: {t.SP_MD}px;"
        )
        self._cl.addWidget(lbl)

    def _h2(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-family: {t.FONT_FAMILY}; "
            f"font-size: 18px; font-weight: 700; "
            f"padding-top: {t.SP_LG}px; padding-bottom: {t.SP_XS}px;"
        )
        self._cl.addWidget(lbl)
        # Hairline under each heading for clear section breaks.
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {t.DIVIDER}; border: none;")
        self._cl.addWidget(rule)

    def _p(self, text: str) -> None:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {t.TEXT_SECONDARY}; font-size: {t.SIZE_BODY}px;"
        )
        self._cl.addWidget(lbl)

    def _ul(self, items: list[str]) -> None:
        for item in items:
            row = QLabel(f"·  {item}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color: {t.TEXT_SECONDARY}; padding-left: {t.SP_SM}px; "
                f"padding-top: 2px; padding-bottom: 2px;"
            )
            self._cl.addWidget(row)

    def _ol(self, items: list[str]) -> None:
        for i, item in enumerate(items, 1):
            row = QLabel(f"{i}.  {item}")
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color: {t.TEXT_SECONDARY}; padding-left: {t.SP_SM}px; "
                f"padding-top: 2px; padding-bottom: 2px;"
            )
            self._cl.addWidget(row)

    def _kv(self, key: str, value: str) -> None:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(t.SP_MD)
        k = QLabel(key)
        k.setStyleSheet(
            f"color: {t.ACCENT_TEXT}; font-weight: 700; font-size: {t.SIZE_BODY}px;"
        )
        k.setMinimumWidth(150)
        k.setMaximumWidth(150)
        v = QLabel(value)
        v.setWordWrap(True)
        v.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
        layout.addWidget(k, 0, Qt.AlignTop)
        layout.addWidget(v, 1)
        self._cl.addWidget(row)

    def _faq(self, q: str, a: str) -> None:
        qlbl = QLabel(q)
        qlbl.setWordWrap(True)
        qlbl.setStyleSheet(
            f"color: {t.TEXT_PRIMARY}; font-weight: 700; "
            f"padding-top: {t.SP_SM}px;"
        )
        self._cl.addWidget(qlbl)
        albl = QLabel(a)
        albl.setWordWrap(True)
        albl.setStyleSheet(f"color: {t.TEXT_SECONDARY};")
        self._cl.addWidget(albl)
