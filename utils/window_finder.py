"""Top-level window enumeration + WM_CLOSE via ctypes (Windows-only).

Used by the Monitor server's `/control/close-window` endpoint to gracefully
close any running RuneScape window when the user taps "Close RuneScape" on
their phone.

WM_CLOSE is a window-level message about closing intent — distinct from
keyboard injection, so NXT's `LLKHF_INJECTED` filter does not apply. This
is the same path the OS uses when you right-click a taskbar icon and pick
"Close window": the game receives the message and may show its own
"are you sure you want to log out?" dialog, which the user can then dismiss
via the Monitor stream if they change their mind.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

_user32 = ctypes.windll.user32
_WM_CLOSE = 0x0010

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
    """Send WM_CLOSE. Does not wait for the window to actually close —
    a graceful close may surface a confirmation dialog the user dismisses
    manually."""
    return bool(_user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0))


def close_all_runescape_windows() -> int:
    """Send WM_CLOSE to every RuneScape window. Returns the count of windows
    posted to (not necessarily the count that actually closed — graceful
    close can be cancelled by the user)."""
    hwnds = find_runescape_windows()
    return sum(1 for h in hwnds if close_window(h))
