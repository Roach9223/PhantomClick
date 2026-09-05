"""Window lock: Zone.rebased math, JSON round trip, and zone_lock.resolve
against a fake window finder. No Qt, no real Win32."""

from __future__ import annotations

import pytest

from modules import zone_lock
from modules.zone_selector import Zone, WindowLock
from utils import window_finder as wf

ANCHOR = (100, 200, 400, 300)          # x, y, w, h at draw time
LOCK = WindowLock(title="RuneScape - Bob", cls="JagWindow", anchor_rect=ANCHOR)


def locked(zone: Zone) -> Zone:
    return zone.with_lock(LOCK)


# rebased

def test_rebased_rect_translates_and_scales_per_axis():
    z = locked(Zone.make_rect(200, 300, 300, 400))   # 100 px in from the anchor corner
    # Window moved by (+300, +120), doubled in width, 1.5x in height.
    out = z.rebased((400, 320, 800, 450))
    assert out.shape == "rect"
    assert out.rect == (600, 470, 800, 620)
    assert out.lock is LOCK
    # The source is untouched.
    assert z.rect == (200, 300, 300, 400)


def test_rebased_circle_uses_mean_scale_for_radius():
    z = locked(Zone.make_circle(300, 350, 40))
    out = z.rebased((400, 320, 800, 450))   # sx = 2.0, sy = 1.5
    assert out.circle == (800, 545, 70)


def test_rebased_polygon_maps_every_vertex():
    z = locked(Zone.make_polygon([(100, 200), (500, 200), (300, 500)]))
    out = z.rebased((0, 0, 800, 600))       # sx = 2.0, sy = 2.0, moved to origin
    assert out.vertices == [(0, 0), (800, 0), (400, 600)]


def test_rebased_pure_translation_keeps_size():
    z = locked(Zone.make_rect(150, 250, 250, 300))
    out = z.rebased((110, 190, 400, 300))
    assert out.rect == (160, 240, 260, 290)


def test_rebased_without_lock_returns_self():
    z = Zone.make_rect(0, 0, 10, 10)
    assert z.rebased((500, 500, 50, 50)) is z


def test_rebased_keeps_drift_state():
    z = locked(Zone.make_rect(0, 0, 10, 10))
    z.drift_offset_x = 3.0
    z.sigma_scale = 1.4
    out = z.rebased(ANCHOR)
    assert out.drift_offset_x == 3.0 and out.sigma_scale == 1.4


# JSON

@pytest.mark.parametrize("zone", [
    Zone.make_rect(1, 2, 30, 40),
    Zone.make_circle(50, 60, 7),
    Zone.make_polygon([(0, 0), (10, 0), (5, 9)]),
], ids=["rect", "circle", "polygon"])
def test_roundtrip_with_lock(zone):
    z = locked(zone)
    d = z.to_json()
    assert d["lock"] == {
        "mode": "window", "title": LOCK.title, "cls": LOCK.cls,
        "anchor_rect": list(ANCHOR),
    }
    back = Zone.from_json(d)
    assert back is not None
    assert back.lock == LOCK
    assert back.to_json() == d


def test_roundtrip_without_lock_has_no_lock_key():
    z = Zone.make_rect(1, 2, 3, 4)
    d = z.to_json()
    assert "lock" not in d
    back = Zone.from_json(d)
    assert back.lock is None and back.to_json() == d


def test_legacy_dict_loads_as_screen_lock():
    d = {"shape": "rect", "rect": [0, 0, 10, 10], "circle": None, "vertices": []}
    z = Zone.from_json(d)
    assert z is not None and z.lock is None
    assert zone_lock.resolve(z, {}).status == "screen"


def test_explicit_screen_mode_loads_as_screen_lock():
    d = {"shape": "rect", "rect": [0, 0, 10, 10], "lock": {"mode": "screen"}}
    z = Zone.from_json(d)
    assert z.lock is None


def test_to_dict_aliases_exist():
    z = Zone.make_rect(0, 0, 1, 1)
    assert Zone.from_dict(z.to_dict()) is not None


# resolve

class FakeDesktop:
    """Stand-in for the Win32 side of utils.window_finder. ``windows`` maps
    hwnd -> dict(title, cls, rect, minimized)."""

    def __init__(self, windows: dict):
        self.windows = windows
        self.find_calls = 0

    def install(self, monkeypatch):
        monkeypatch.setattr(wf, "is_window", lambda h: h in self.windows)
        monkeypatch.setattr(wf, "window_info", self.window_info)
        monkeypatch.setattr(wf, "find_window", self.find_window)
        monkeypatch.setattr(wf, "is_minimized",
                            lambda h: bool(self.windows.get(h, {}).get("minimized")))
        monkeypatch.setattr(wf, "window_rect_dip",
                            lambda h: self.windows[h]["rect"] if h in self.windows else None)
        monkeypatch.setattr(wf, "window_at_point", lambda x, y: None)

    def window_info(self, hwnd):
        w = self.windows.get(hwnd)
        if w is None:
            return None
        return wf.WindowInfo(hwnd=hwnd, title=w["title"], cls=w["cls"], pid=4242,
                             rect_dip=w["rect"])

    def find_window(self, title, cls):
        self.find_calls += 1
        for h, w in self.windows.items():
            if w["cls"] == cls and (w["title"] == title or title.lower() in w["title"].lower()):
                return self.window_info(h)
        return None


def test_resolve_screen_zone_passes_through():
    z = Zone.make_rect(0, 0, 10, 10)
    res = zone_lock.resolve(z, {})
    assert res.status == "screen" and res.zone is z and res.window is None


def test_resolve_locked_rebases_and_caches_hwnd(monkeypatch):
    desk = FakeDesktop({7: {"title": LOCK.title, "cls": LOCK.cls, "rect": (400, 320, 600, 450)}})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    cache: dict = {}
    res = zone_lock.resolve(z, cache)
    assert res.status == "locked"
    assert res.zone.rect == (550, 470, 700, 620)
    assert res.window.hwnd == 7
    assert cache[(LOCK.title, LOCK.cls)] == 7
    # Second resolve reuses the hwnd; no enumeration.
    zone_lock.resolve(z, cache)
    assert desk.find_calls == 1


def test_resolve_lost_returns_original_zone(monkeypatch):
    desk = FakeDesktop({})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    res = zone_lock.resolve(z, {})
    assert res.status == "lost"
    assert res.zone is z
    assert res.holding
    assert res.title == LOCK.title


def test_resolve_minimized(monkeypatch):
    desk = FakeDesktop({7: {"title": LOCK.title, "cls": LOCK.cls,
                            "rect": (0, 0, 400, 300), "minimized": True}})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    res = zone_lock.resolve(z, {})
    assert res.status == "minimized" and res.holding
    assert res.zone is z
    assert res.window.hwnd == 7


def test_resolve_keeps_live_hwnd_through_title_change(monkeypatch):
    desk = FakeDesktop({
        7: {"title": "RuneScape - Bob", "cls": "JagWindow", "rect": (100, 200, 400, 300)},
    })
    desk.install(monkeypatch)
    # Fresh lock object: the rename mutates lock.title in place and the
    # module-level LOCK is shared by every other test here.
    lock = WindowLock(title="RuneScape - Bob", cls="JagWindow", anchor_rect=ANCHOR)
    z = Zone.make_rect(200, 300, 300, 400).with_lock(lock)
    cache: dict = {}
    assert zone_lock.resolve(z, cache).status == "locked"
    assert desk.find_calls == 1
    # Login screen -> in game: the title bar changes, the window does not.
    desk.windows[7]["title"] = "RuneScape - Alice (World 84)"
    res = zone_lock.resolve(z, cache)
    assert res.status == "locked"
    assert res.window.hwnd == 7
    assert res.title == "RuneScape - Alice (World 84)"
    # No re-enumeration, the lock now names the new title, and the cache
    # is keyed by it so the next resolve is still a cache hit.
    assert desk.find_calls == 1
    assert lock.title == "RuneScape - Alice (World 84)"
    assert cache == {("RuneScape - Alice (World 84)", "JagWindow"): 7}
    zone_lock.resolve(z, cache)
    assert desk.find_calls == 1


def test_resolve_drops_cached_hwnd_when_class_changes(monkeypatch):
    desk = FakeDesktop({
        7: {"title": LOCK.title, "cls": LOCK.cls, "rect": (100, 200, 400, 300)},
    })
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    cache: dict = {}
    assert zone_lock.resolve(z, cache).status == "locked"
    # hwnd 7 was recycled by another program; the real one is hwnd 9.
    desk.windows[7] = {"title": LOCK.title, "cls": "Notepad", "rect": (0, 0, 10, 10)}
    desk.windows[9] = {"title": LOCK.title, "cls": LOCK.cls, "rect": (100, 200, 400, 300)}
    res = zone_lock.resolve(z, cache)
    assert res.status == "locked"
    assert res.window.hwnd == 9
    assert cache[(LOCK.title, LOCK.cls)] == 9


def test_resolve_drops_cached_hwnd_when_window_closes(monkeypatch):
    desk = FakeDesktop({7: {"title": LOCK.title, "cls": LOCK.cls, "rect": (100, 200, 400, 300)}})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    cache: dict = {}
    zone_lock.resolve(z, cache)
    del desk.windows[7]
    res = zone_lock.resolve(z, cache)
    assert res.status == "lost"
    assert (LOCK.title, LOCK.cls) not in cache


def test_resolver_keeps_last_known_position_while_lost(monkeypatch):
    desk = FakeDesktop({7: {"title": LOCK.title, "cls": LOCK.cls, "rect": (400, 320, 400, 300)}})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    r = zone_lock.LockResolver(max_hz=0)
    first = r.resolve(z, key="main")
    assert first.status == "locked" and first.zone.rect == (500, 420, 600, 520)
    del desk.windows[7]
    lost = r.resolve(z, key="main")
    assert lost.status == "lost"
    assert lost.zone.rect == (500, 420, 600, 520)


def test_attach_window_lock_uses_window_under_centre(monkeypatch):
    monkeypatch.setattr(zone_lock.dpi_cursor, "dip_to_physical", lambda x, y: (x, y))
    seen = {}

    def fake_at(x, y):
        seen["pt"] = (x, y)
        return wf.WindowInfo(hwnd=3, title="Game", cls="GameCls", pid=1, rect_dip=(10, 20, 300, 200))

    monkeypatch.setattr(wf, "window_at_point", fake_at)
    z = Zone.make_rect(100, 100, 200, 150)
    out = zone_lock.attach_window_lock(z)
    assert seen["pt"] == (150, 125)
    assert out.lock == WindowLock("Game", "GameCls", (10, 20, 300, 200))
    assert out.rect == z.rect


def test_attach_window_lock_over_desktop_stays_screen(monkeypatch):
    monkeypatch.setattr(zone_lock.dpi_cursor, "dip_to_physical", lambda x, y: (x, y))
    monkeypatch.setattr(wf, "window_at_point", lambda x, y: None)
    out = zone_lock.attach_window_lock(locked(Zone.make_rect(0, 0, 10, 10)).with_lock(None))
    assert out.lock is None


def test_apply_lock_mode_screen_pins_current_position(monkeypatch):
    desk = FakeDesktop({7: {"title": LOCK.title, "cls": LOCK.cls, "rect": (400, 320, 400, 300)}})
    desk.install(monkeypatch)
    z = locked(Zone.make_rect(200, 300, 300, 400))
    out = zone_lock.apply_lock_mode(z, "screen")
    assert out.lock is None
    assert out.rect == (500, 420, 600, 520)


def test_retarget_lock_keeps_relative_place_and_switches_window():
    from types import SimpleNamespace
    from modules.zone_lock import retarget_lock
    from modules.zone_selector import WindowLock, Zone
    # Zone at the top-left quarter of a 1000 x 500 window at (0, 0).
    zone = Zone.make_rect(100, 50, 300, 150).with_lock(
        WindowLock(title="VirtualBox", cls="QWidget", anchor_rect=(0, 0, 1000, 500)))
    rs = SimpleNamespace(title="RuneScape", cls="JagWindow", rect_dip=(2000, 100, 500, 250))
    moved = retarget_lock(zone, rs)
    assert moved.lock.title == "RuneScape" and moved.lock.cls == "JagWindow"
    assert moved.lock.anchor_rect == (2000, 100, 500, 250)
    # Half the size, shifted: same corner of the new window.
    assert moved.rect == (2050, 125, 2150, 175)
    # An unlocked zone keeps its screen position and just gains the lock.
    flat = Zone.make_rect(10, 10, 20, 20)
    locked = retarget_lock(flat, rs)
    assert locked.rect == (10, 10, 20, 20) and locked.lock.title == "RuneScape"
    # A bad rect leaves the zone alone.
    assert retarget_lock(zone, SimpleNamespace(title="x", cls="y", rect_dip=(0, 0, 0, 0))) is zone
