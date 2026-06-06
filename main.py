"""PhantomClick entry point."""

import sys


def _enable_dpi_awareness() -> None:
    """Tell Windows we handle our own DPI so Tk reports true pixel dimensions.

    Without this, on a 125%/150%-scaled monitor Tk's `winfo_screenwidth()`
    returns the scaled (virtual) size, the draw/zone overlay doesn't cover
    the whole monitor, and click coordinates drift out of the zone because
    pynput operates in physical pixels. Must run before any Tk import/call.
    """
    if sys.platform != "win32":
        return
    import ctypes
    # Preferred: per-monitor-v2 (Win10 1703+). Falls back to per-monitor, then system.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_enable_dpi_awareness()

from app import run

if __name__ == "__main__":
    run()
