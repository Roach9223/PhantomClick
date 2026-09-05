"""PhantomClick entry point."""

import sys


def _enable_dpi_awareness() -> None:
    """Opt the process into per-monitor DPI awareness before Qt loads.

    pynput and mss work in physical pixels. If Windows is left to
    virtualize DPI for us, a 125% or 150% monitor reports scaled
    coordinates, the fullscreen zone overlays stop covering the whole
    screen, and clicks land outside the zone the user drew. Qt reads the
    process awareness at QApplication creation, so this has to run before
    ``app`` (and therefore PySide6) is imported.
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


# Bundled font files, relative to the install root. JetBrains Mono is the UI
# face, Barlow is the wordmark. Both are OFL; licences sit next to them.
_FONT_FILES = (
    "ui/fonts/JetBrainsMono-Regular.ttf",
    "ui/fonts/JetBrainsMono-Medium.ttf",
    "ui/fonts/JetBrainsMono-SemiBold.ttf",
    "ui/fonts/Barlow-Medium.ttf",
    "ui/fonts/Barlow-SemiBold.ttf",
    "ui/fonts/Barlow-Bold.ttf",
)


def load_fonts() -> list[str]:
    """Register the bundled fonts with Qt. Returns the family names that
    loaded. Needs a live QGuiApplication, so call it after the
    QApplication exists and before the main window is built. A missing or
    unreadable file is skipped; the theme's font stacks fall back to
    Cascadia Mono / Consolas / Segoe UI.
    """
    from PySide6.QtGui import QFontDatabase
    from utils.paths import bundled_root

    root = bundled_root()
    families: list[str] = []
    for rel in _FONT_FILES:
        path = root / rel
        if not path.is_file():
            continue
        try:
            fid = QFontDatabase.addApplicationFont(str(path))
        except Exception:
            continue
        if fid < 0:
            continue
        for fam in QFontDatabase.applicationFontFamilies(fid):
            if fam not in families:
                families.append(fam)
    return families


def apply_app_font(qt_app, families: list[str]) -> None:
    """Install the UI face as the application font.

    Widgets inherit family, size, weight and, importantly, the hinting
    preference from here; the stylesheet overrides family, size and
    weight only per role, never on the universal QWidget selector (a
    stylesheet font beats setFont, so a universal rule would flatten
    every custom-sized label). Full hinting snaps stems to whole pixels,
    which is what keeps 12 to 13 px text sharp on a 100 % monitor instead
    of the soft grey DirectWrite renders with no hinting.
    """
    from PySide6.QtGui import QFont
    from ui import theme as t

    # Barlow is the UI face (labels, buttons, prose); JetBrains Mono is
    # set per widget for values. Segoe UI is the Windows fallback when the
    # bundled file did not register.
    family = "Barlow" if "Barlow" in families else "Segoe UI"
    font = QFont(family)
    font.setPixelSize(int(t.SIZE_BODY))
    font.setWeight(QFont.Weight(int(t.FONT_WEIGHT_BODY)))
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    qt_app.setFont(font)


def main() -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    # PassThrough keeps a 150% monitor at exactly 1.5x instead of rounding
    # it to 2x, so logical sizes match what Windows reports and the deck
    # viewport's device-pixel maths line up with the real screen. Must be
    # set before the QApplication exists.
    if QApplication.instance() is None:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # Create the QApplication here so the fonts register before ui.app
    # constructs any widget. ``run()`` reuses the existing instance.
    qt_app = QApplication.instance() or QApplication(sys.argv)
    loaded = load_fonts()
    apply_app_font(qt_app, loaded)
    try:
        from utils.logger import get_logger
        get_logger().info("fonts loaded: %s", ", ".join(loaded) or "none")
    except Exception:
        pass
    _ = qt_app

    from app import run
    run()


if __name__ == "__main__":
    main()
