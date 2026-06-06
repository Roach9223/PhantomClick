"""Win11 native chrome — Mica backdrop + dark title bar via DwmSetWindowAttribute.

Both calls are silent no-ops on non-Windows or Windows builds that don't
support the attribute (Win10, early Win11). Returns ``True`` on success so
callers can decide whether to fall back to a solid window background.

DWM attribute IDs come from ``dwmapi.h`` in the Windows SDK:
- ``DWMWA_USE_IMMERSIVE_DARK_MODE = 20`` — forces dark non-client area
- ``DWMWA_SYSTEMBACKDROP_TYPE = 38`` — Mica / Acrylic / Tabbed (Win11 22H2+)

We only enable Mica (``DWMSBT_MAINWINDOW = 2``); Acrylic on the main window
looks dated and Tabbed-Mica is for tabbed shells like Explorer.
"""

from __future__ import annotations

import ctypes
import sys


_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2


def _dwm():
    """Return the ``DwmSetWindowAttribute`` function pointer with proper
    argtypes set, or ``None`` on non-Windows / missing dwmapi.
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes
        fn = ctypes.windll.dwmapi.DwmSetWindowAttribute
        fn.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ]
        fn.restype = ctypes.c_long
        return fn
    except (AttributeError, OSError, ImportError):
        return None


def _set_attr(hwnd: int, attr: int, value: int) -> bool:
    fn = _dwm()
    if fn is None:
        return False
    try:
        val = ctypes.c_int(int(value))
        hr = fn(int(hwnd), int(attr), ctypes.byref(val), ctypes.sizeof(val))
        return hr == 0
    except Exception:
        return False


def apply_dark_titlebar(hwnd: int) -> bool:
    """Force the title bar into dark mode regardless of the system theme.

    Returns True on success. No-op on non-Windows or unsupported builds.
    """
    return _set_attr(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1)


def apply_mica(hwnd: int) -> bool:
    """Enable Mica backdrop on the window.

    Requires Windows 11 22H2 (build 22621) or newer. Returns True on success.
    On older builds the call returns nonzero and we silently fall back to
    whatever solid color the window paints itself.
    """
    return _set_attr(hwnd, _DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_MAINWINDOW)
