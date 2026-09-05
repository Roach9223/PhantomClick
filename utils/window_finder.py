"""Top-level window enumeration + WM_CLOSE via ctypes (Windows-only).

Used by the Monitor server's `/control/close-window` endpoint to gracefully
close any running RuneScape window when the user taps "Close RuneScape" on
their phone.

WM_CLOSE is a window-level message about closing intent, distinct from
keyboard injection, so NXT's `LLKHF_INJECTED` filter does not apply. This
is the same path the OS uses when you right-click a taskbar icon and pick
"Close window": the game receives the message and may show its own
"are you sure you want to log out?" dialog, which the user can then dismiss
via the Monitor stream if they change their mind.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Optional

_user32 = ctypes.windll.user32
_WM_CLOSE = 0x0010
_GA_ROOT = 2
_GW_HWNDNEXT = 2
_DWMWA_CLOAKED = 14
_DWMWA_EXTENDED_FRAME_BOUNDS = 9
# Desktop and taskbar classes: a zone drawn over bare wallpaper must stay
# screen-locked instead of riding the shell.
_SHELL_CLASSES = frozenset({"Progman", "WorkerW", "Shell_TrayWnd",
                            "Shell_SecondaryTrayWnd"})

try:
    _dwmapi = ctypes.windll.dwmapi
except Exception:  # pragma: no cover - DWM is present on every supported OS
    _dwmapi = None

# EnumWindows callback signature: BOOL CALLBACK EnumWindowsProc(HWND, LPARAM)
_EnumWindowsProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
)

_user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
]
_user32.PostMessageW.restype = wintypes.BOOL


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def enumerate_windows() -> list[tuple[int, str]]:
    """Return [(hwnd, title)] for every visible top-level window with a non-empty title."""
    results: list[tuple[int, str]] = []

    def _cb(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _window_title(hwnd)
        if title:
            results.append((int(hwnd), title))
        return True

    _user32.EnumWindows(_EnumWindowsProc(_cb), 0)
    return results


def find_windows_by_title(predicate: Callable[[str], bool]) -> list[int]:
    return [hwnd for hwnd, title in enumerate_windows() if predicate(title)]


def find_runescape_windows() -> list[int]:
    needle = "runescape"
    return find_windows_by_title(lambda t: needle in t.lower())


def close_window(hwnd: int) -> bool:
    """Send WM_CLOSE. Does not wait for the window to actually close , 
    a graceful close may surface a confirmation dialog the user dismisses
    manually."""
    return bool(_user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0))


def close_all_runescape_windows() -> int:
    """Send WM_CLOSE to every RuneScape window. Returns the count of windows
    posted to (not necessarily the count that actually closed, graceful
    close can be cancelled by the user)."""
    hwnds = find_runescape_windows()
    return sum(1 for h in hwnds if close_window(h))


# Window lock support

class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = [_POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetTopWindow.argtypes = [wintypes.HWND]
_user32.GetTopWindow.restype = wintypes.HWND
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    cls: str
    pid: int
    rect_dip: tuple[int, int, int, int]   # (x, y, w, h)
    exe: str = ""                          # process image name, e.g. "rs2client.exe"
    minimized: bool = False

    @property
    def label(self) -> str:
        """``Title  ·  exe`` for pickers; the title alone when the exe is
        unknown; a minimised window says so."""
        title = self.title or self.cls or "(untitled window)"
        out = f"{title}  ·  {self.exe}" if self.exe else title
        return out + "  ·  minimised" if self.minimized else out


_kernel32 = ctypes.windll.kernel32
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_name(pid: int) -> str:
    """Image file name of ``pid`` ("rs2client.exe"), or "" when the
    process cannot be opened (elevated, gone)."""
    try:
        h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            _kernel32.CloseHandle(h)
    except Exception:
        return ""


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    n = _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if n > 0 else ""


def _pid_of(hwnd: int) -> int:
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _is_cloaked(hwnd: int) -> bool:
    """UWP frame hosts and suspended store apps keep an invisible window
    on the z-order; DWM reports those as cloaked."""
    if _dwmapi is None:
        return False
    try:
        val = wintypes.DWORD(0)
        hr = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), wintypes.DWORD(_DWMWA_CLOAKED),
            ctypes.byref(val), ctypes.sizeof(val))
        return hr == 0 and val.value != 0
    except Exception:
        return False


def _physical_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """Window rect in physical pixels as ``(left, top, right, bottom)``.

    Prefers the DWM extended frame bounds, which exclude the invisible
    resize border Windows 10/11 adds around themed windows. Without that
    the anchor rect would be ~7 px too large on each side and the rebased
    zone would land slightly off after a resize.
    """
    r = _RECT()
    if _dwmapi is not None:
        try:
            hr = _dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), wintypes.DWORD(_DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(r), ctypes.sizeof(r))
            if hr == 0 and r.right > r.left and r.bottom > r.top:
                return (r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
    if not _user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", _POINT),
                ("ptMaxPosition", _POINT), ("rcNormalPosition", _RECT)]


def normal_rect_dip(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """``(x, y, w, h)`` in DIPs of where the window sits when restored.
    A minimised window's live rect is an off-screen placeholder, so a
    lock anchored there would be useless; this is what the anchor uses
    instead."""
    try:
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(wp)
        if not _user32.GetWindowPlacement(int(hwnd), ctypes.byref(wp)):
            return None
        r = wp.rcNormalPosition
        if r.right <= r.left or r.bottom <= r.top:
            return None
        from . import dpi_cursor
        x1, y1 = dpi_cursor.physical_to_dip(r.left, r.top)
        x2, y2 = dpi_cursor.physical_to_dip(r.right, r.bottom)
        return (int(x1), int(y1), int(x2 - x1), int(y2 - y1))
    except Exception:
        return None


def window_rect_dip(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """``(x, y, w, h)`` of the window in DIPs, or None on any failure."""
    try:
        phys = _physical_rect(int(hwnd))
        if phys is None:
            return None
        from . import dpi_cursor
        left, top, right, bottom = phys
        x1, y1 = dpi_cursor.physical_to_dip(left, top)
        # Convert the far corner through the same screen as the near one
        # so a window straddling a DPI boundary does not get a mangled size.
        s = dpi_cursor._screen_for_physical(left, top)
        if s is not None:
            dpr = s["dpr"]
            w = int(round((right - left) / dpr))
            h = int(round((bottom - top) / dpr))
        else:
            x2, y2 = dpi_cursor.physical_to_dip(right, bottom)
            w, h = x2 - x1, y2 - y1
        if w <= 0 or h <= 0:
            return None
        return (int(x1), int(y1), int(w), int(h))
    except Exception:
        return None


def is_minimized(hwnd: int) -> bool:
    try:
        return bool(_user32.IsIconic(int(hwnd)))
    except Exception:
        return False


def is_window(hwnd: int) -> bool:
    try:
        return bool(_user32.IsWindow(int(hwnd)))
    except Exception:
        return False


def window_info(hwnd: int, *, with_exe: bool = False) -> Optional[WindowInfo]:
    """Snapshot of one top-level window, or None if it is gone. The exe
    name costs an OpenProcess, so it is only filled in on request."""
    try:
        hwnd = int(hwnd)
        if not _user32.IsWindow(hwnd):
            return None
        rect = window_rect_dip(hwnd) or (0, 0, 0, 0)
        pid = _pid_of(hwnd)
        return WindowInfo(hwnd=hwnd, title=_window_title(hwnd), cls=_class_name(hwnd),
                          pid=pid, rect_dip=rect, exe=process_name(pid) if with_exe else "")
    except Exception:
        return None


def list_lock_targets() -> list[WindowInfo]:
    """Every window a zone could lock to, in z-order (front first): visible,
    titled, not ours, not the shell, not a cloaked ghost. Minimised windows
    are included so a user can pick a game they have tucked away; the lock
    holds until it comes back."""
    out: list[WindowInfo] = []
    try:
        h = _user32.GetTopWindow(None)
        guard = 0
        while h and guard < 4096:
            guard += 1
            if _acceptable_lock_target(h) and _window_title(h):
                info = window_info(int(h), with_exe=True)
                if info is not None and is_minimized(int(h)):
                    rect = normal_rect_dip(int(h))
                    if rect is not None:
                        info = WindowInfo(hwnd=info.hwnd, title=info.title, cls=info.cls,
                                          pid=info.pid, rect_dip=rect, exe=info.exe,
                                          minimized=True)
                if info is not None and info.rect_dip and info.rect_dip[2] > 0:
                    out.append(info)
            h = _user32.GetWindow(h, _GW_HWNDNEXT)
    except Exception:
        pass
    return out


def _acceptable_lock_target(hwnd: int) -> bool:
    """A window a zone may lock onto: not ours, not the shell, not a
    cloaked ghost, actually visible."""
    if not hwnd or not _user32.IsWindowVisible(hwnd):
        return False
    if _pid_of(hwnd) == os.getpid():
        return False
    if _class_name(hwnd) in _SHELL_CLASSES:
        return False
    if _is_cloaked(hwnd):
        return False
    return True


def window_at_point(x_phys: int, y_phys: int) -> Optional[WindowInfo]:
    """Top-level window under a physical-pixel point, skipping PhantomClick's
    own windows and the desktop / taskbar.

    WindowFromPoint is tried first. When it lands on one of our windows
    (the main window is often restored over the zone when this runs) the
    z-order is walked top-down for the first acceptable window whose rect
    contains the point, which is what a user "sees through" our window.
    """
    try:
        pt = _POINT(int(x_phys), int(y_phys))
        hwnd = _user32.WindowFromPoint(pt)
        if hwnd:
            root = _user32.GetAncestor(hwnd, _GA_ROOT) or hwnd
            if _acceptable_lock_target(root):
                return window_info(int(root))
        h = _user32.GetTopWindow(None)
        guard = 0
        while h and guard < 4096:
            guard += 1
            if _acceptable_lock_target(h):
                rect = _physical_rect(h)
                if rect is not None:
                    l, t, r, b = rect
                    if l <= x_phys < r and t <= y_phys < b:
                        return window_info(int(h))
            h = _user32.GetWindow(h, _GW_HWNDNEXT)
        return None
    except Exception:
        return None


def find_window(title: str, cls: str) -> Optional[WindowInfo]:
    """Locate a window by (title, class), tolerant of small title changes.

    Order: exact title + class, then case-insensitive contains (either
    direction) with the same class, then class alone when exactly one
    window has it. Visible, non-minimized windows win over minimized
    ones at every stage so a stray minimized duplicate does not hijack
    the lock. Returns None when nothing matches.
    """
    try:
        title = str(title or "")
        cls = str(cls or "")
        needle = title.lower()
        own_pid = os.getpid()
        exact: list[int] = []
        loose: list[int] = []
        by_class: list[int] = []

        def _cb(hwnd: int, _lparam: int) -> bool:
            if _pid_of(hwnd) == own_pid or _class_name(hwnd) != cls:
                return True
            if _class_name(hwnd) in _SHELL_CLASSES or _is_cloaked(hwnd):
                return True
            by_class.append(int(hwnd))
            t = _window_title(hwnd)
            if t == title and title:
                exact.append(int(hwnd))
            elif needle and (needle in t.lower() or (t and t.lower() in needle)):
                loose.append(int(hwnd))
            return True

        _user32.EnumWindows(_EnumWindowsProc(_cb), 0)

        def _rank(h: int) -> tuple[int, int]:
            vis = bool(_user32.IsWindowVisible(h))
            mini = bool(_user32.IsIconic(h))
            return (0 if vis else 1, 1 if mini else 0)

        for bucket in (exact, loose):
            if bucket:
                bucket.sort(key=_rank)
                return window_info(bucket[0])
        if cls and len(by_class) == 1:
            return window_info(by_class[0])
        return None
    except Exception:
        return None
