"""Right-click menus for the deck.

One place builds them so the viewport, the SEQUENCE panel and the zone
map offer the same verbs with the same wording. Every action routes
through the same App / editor methods the buttons use, so a menu never
has its own behaviour to keep in step.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from modules.clicker import ClickerState
from modules.recorder import KIND_CLICK, RecorderStep
from modules.zone_selector import Zone

from ui import icons, theme as t

# Side of the square area the "put a click area here" verb creates.
QUICK_AREA_PX = 60


def _step_index(app, step_id: Optional[str]) -> Optional[int]:
    if not step_id:
        return None
    for i, s in enumerate(app._steps):
        if s.step_id == step_id:
            return i
    return None


def _quick_zone(app, x: int, y: int) -> Zone:
    half = QUICK_AREA_PX // 2
    zone = Zone.make_rect(int(x) - half, int(y) - half, int(x) + half, int(y) + half)
    if str(app.cfg.get("zone_lock_default", "window")) == "window":
        try:
            from modules.zone_lock import apply_lock_mode
            zone = apply_lock_mode(zone, "window")
        except Exception:
            pass
    return zone


def place_click_area(app, x: int, y: int) -> None:
    """Put a QUICK_AREA_PX square centred on DIP (x, y). Click mode: it
    becomes the click area. Record mode: it goes on the selected (else
    expanded, else first) Click step, or a new Click step is appended."""
    from ui.config_io import save_config
    zone = _quick_zone(app, x, y)
    if app._active_mode != "recorder":
        app._zone = zone
        app.cfg["zone"] = zone.to_json()
        save_config(app.cfg)
        try:
            app.zone_locks.forget("main")
        except Exception:
            pass
        try:
            app.click_page.zone_card._refresh_preview()
        except Exception:
            pass
        app._push_config_to_clicker()
        app.overlay_manager.apply_visibility()
        return
    tab = app.record_mode_tab
    idx = _step_index(app, tab.selected_step_id())
    if idx is None or app._steps[idx].kind != KIND_CLICK:
        idx = None
        expanded = tab._row_builder._expanded
        for i, s in enumerate(app._steps):
            if s.kind == KIND_CLICK and s.step_id in expanded:
                idx = i
        if idx is None:
            app._steps.append(RecorderStep(kind=KIND_CLICK, zone=zone))
            app._save_steps()
            tab._after_add()
            app.overlay_manager.refresh_step_overlays()
            app.toasts.post(f"Added Click step {len(app._steps)} at ({x}, {y}).", kind="info")
            return
    app._steps[idx].zone = zone
    app._save_steps()
    try:
        app.zone_locks.forget(app._steps[idx].step_id)
    except Exception:
        pass
    tab.render_all()
    app.overlay_manager.refresh_step_overlays()
    app.toasts.post(f"Click step {idx + 1} moved to ({x}, {y}).", kind="info")


def _add_zoom_menu(menu: QMenu, viewport) -> None:
    sub = menu.addMenu("Zoom")
    try:
        levels = viewport.zoom_levels()
        cur = viewport.zoom()
    except Exception:
        return
    for i, z in enumerate(levels):
        act = QAction(f"{z:g}x", sub)
        act.setCheckable(True)
        act.setChecked(abs(z - cur) < 1e-6)
        act.triggered.connect(lambda _c=False, n=i: viewport.set_zoom_index(n))
        sub.addAction(act)


def add_monitor_menu(menu: QMenu, app) -> None:
    sub = menu.addMenu("Target monitor")
    idx = app._explicit_target_screen_index()
    cur = "auto" if idx is None else str(idx)
    auto = QAction("Auto (follow the click area)", sub)
    auto.setCheckable(True)
    auto.setChecked(cur == "auto")
    auto.triggered.connect(lambda: app.set_target_monitor("auto"))
    sub.addAction(auto)
    sub.addSeparator()
    try:
        screens = list(QApplication.instance().screens())
    except Exception:
        screens = []
    for i, s in enumerate(screens):
        g = s.geometry()
        act = QAction(f"MON{i + 1}  {g.width()} x {g.height()}", sub)
        act.setCheckable(True)
        act.setChecked(cur == str(i))
        act.triggered.connect(lambda _c=False, n=i: app.set_target_monitor(n))
        sub.addAction(act)


def viewport_menu(app, viewport, dip: Optional[tuple[int, int]],
                  parent: Optional[QWidget] = None) -> QMenu:
    """Menu for a right-click on the live viewport. ``dip`` is the screen
    point under the cursor, or None when the click was off the frame."""
    menu = QMenu(parent)
    recorder = app._active_mode == "recorder"
    idle = app._state_str == ClickerState.IDLE

    if dip is not None:
        x, y = dip
        here = QAction(icons.icon("target"),
                       f"Put a {QUICK_AREA_PX} x {QUICK_AREA_PX} click area here  ({x}, {y})", menu)
        here.setEnabled(idle)
        here.triggered.connect(lambda: place_click_area(app, x, y))
        menu.addAction(here)

    draw = QAction(icons.icon("redraw"), "Draw click area on screen", menu)
    draw.setEnabled(idle)

    def _draw():
        if recorder:
            app.record_mode_tab.on_add_click()
            app.record_mode_tab._row_builder._on_draw_step(len(app._steps) - 1)
        else:
            app.click_page.zone_card._on_draw()
    draw.triggered.connect(_draw)
    menu.addAction(draw)

    if recorder:
        add = menu.addMenu(icons.icon("plus"), "Add step")
        tab = app.record_mode_tab
        for icon, label, fn in (
            ("click", "Click", tab.on_add_click),
            ("target", "Track", tab.on_add_track),
            ("dot", "Color", tab.on_add_color),
            ("key", "Keyboard", tab.on_add_key),
            ("pause", "Pause", tab.on_add_pause),
            ("loop", "Loop", tab.on_add_loop),
        ):
            act = QAction(icons.icon(icon), label, add)
            act.setEnabled(idle)
            act.triggered.connect(lambda _c=False, f=fn: f())
            add.addAction(act)

    menu.addSeparator()
    show = QAction("Show outline on screen", menu)
    show.setCheckable(True)
    show.setChecked(bool(app.cfg.get("show_zone_overlay", True)))
    show.triggered.connect(lambda on: app.set_overlay_visible(bool(on)))
    menu.addAction(show)
    _add_zoom_menu(menu, viewport)
    add_monitor_menu(menu, app)

    menu.addSeparator()
    deck = getattr(app, "deck", None)
    if deck is not None:
        label = {"clicker": "SETUP", "recorder": "STEPS", "ai": "BOT"}.get(app._active_mode, "pane")
        pane = QAction(icons.icon("edit"), f"Open the {label} pane", menu)
        pane.triggered.connect(lambda: deck.set_editor_open(True))
        menu.addAction(pane)
    return menu


def step_row_menu(app, step_id: str, parent: Optional[QWidget] = None) -> Optional[QMenu]:
    """Menu for a right-click on a SEQUENCE row that stands for a step."""
    idx = _step_index(app, step_id)
    if idx is None:
        return None
    step = app._steps[idx]
    tab = app.record_mode_tab
    builder = tab._row_builder
    idle = app._state_str == ClickerState.IDLE
    menu = QMenu(parent)

    edit_act = QAction(icons.icon("edit"), f"Edit step {idx + 1}", menu)
    edit_act.triggered.connect(lambda: (app.deck.set_editor_open(True), tab.select_step(step_id)))
    menu.addAction(edit_act)

    on = QAction("Enabled", menu)
    on.setCheckable(True)
    on.setChecked(bool(getattr(step, "enabled", True)))

    def _toggle(checked: bool) -> None:
        step.enabled = bool(checked)
        app.save_steps_later()
        tab.render_all()
    on.triggered.connect(_toggle)
    menu.addAction(on)
    menu.addSeparator()

    for icon, text, fn, enabled in (
        ("arrow-up", "Move up", lambda: builder._move(idx, -1, tab.render_all), idx > 0),
        ("arrow-down", "Move down", lambda: builder._move(idx, +1, tab.render_all), idx < len(app._steps) - 1),
        ("duplicate", "Duplicate", lambda: builder._duplicate(idx, tab.render_all), True),
    ):
        act = QAction(icons.icon(icon), text, menu)
        act.setEnabled(bool(enabled) and idle)
        act.triggered.connect(lambda _c=False, f=fn: f())
        menu.addAction(act)
    menu.addSeparator()
    rm = QAction(icons.icon("trash", 16, t.DANGER), "Remove step", menu)
    rm.setEnabled(idle)
    rm.triggered.connect(lambda: builder._remove(idx, tab.render_all))
    menu.addAction(rm)
    return menu


def click_zone_menu(app, parent: Optional[QWidget] = None) -> QMenu:
    """Menu for the SEQUENCE panel's ZONE row in Click mode."""
    menu = QMenu(parent)
    card = app.click_page.zone_card
    draw = QAction(icons.icon("redraw"), "Redraw click area", menu)
    draw.triggered.connect(card._on_draw)
    menu.addAction(draw)
    clear = QAction(icons.icon("trash", 16, t.DANGER), "Clear click area", menu)
    clear.setEnabled(app._zone is not None)
    clear.triggered.connect(card._on_clear)
    menu.addAction(clear)
    menu.addSeparator()
    show = QAction("Show outline on screen", menu)
    show.setCheckable(True)
    show.setChecked(bool(app.cfg.get("show_zone_overlay", True)))
    show.triggered.connect(lambda on: app.set_overlay_visible(bool(on)))
    menu.addAction(show)
    return menu
