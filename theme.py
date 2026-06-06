"""Color palette, fonts, and spacing for PhantomClick.

Refreshed 2026: warm-neutral slate surfaces (no blue cast), a slightly
desaturated coral accent for lower eye strain over long sessions, and
Segoe UI Variable for body / display type on Windows 11.
"""

# -- Surfaces ---------------------------------------------------------------
BG = "#0d0f12"            # window background
CARD_BG = "#15181d"       # primary card surface
SURFACE_HIGH = "#1d2128"  # entries, button hovers on dark, second-elevation surfaces
CARD_BORDER = "#252a32"   # 1px border on cards / dividers
DIVIDER = "#1f232a"       # subtle row separators

# -- Accent (primary brand colour) -----------------------------------------
ACCENT = "#22d3ee"        # teal-cyan (was coral #ff5470)
ACCENT_HOVER = "#38e6ff"
ACCENT_PRESSED = "#06b6d4"

# -- Status & semantic colours ---------------------------------------------
START = "#34d399"         # green start button
START_HOVER = "#2ec07e"
STOP = ACCENT             # stop button = accent
STOP_HOVER = ACCENT_HOVER
DANGER_DEEP = "#9a3346"   # destructive hover (⨯ remove buttons)

HOVER_ACCENT = "#5b8def"  # secondary accent (Add Hover Zone)
HOVER_ACCENT_HOVER = "#4a78dc"

STATUS_ACTIVE = "#34d399"
STATUS_IDLE = "#71717a"
STATUS_PAUSED = "#fbbf24"

# -- Text -------------------------------------------------------------------
TEXT_PRIMARY = "#ededed"
TEXT_SECONDARY = "#9ca3af"
TEXT_TERTIARY = "#6b7280"

# -- Sliders ----------------------------------------------------------------
SLIDER_TRACK = "#252a32"
SLIDER_THUMB = ACCENT

# -- Typography ------------------------------------------------------------
# Segoe UI Variable ships with Windows 11. If absent, Tk silently falls back
# to Segoe UI (Win10) or the system default — string-name lookup never errors.
FONT_FAMILY = "Segoe UI Variable Text"
FONT_DISPLAY = "Segoe UI Variable Display"
FONT_MONO_FAMILY = "Cascadia Mono"  # Win10+ default; falls back to Consolas

FONT_TITLE = (FONT_DISPLAY, 22, "bold")
FONT_CARD_HEADER = (FONT_DISPLAY, 12, "bold")
FONT_VALUE = (FONT_FAMILY, 15)
FONT_LABEL = (FONT_FAMILY, 13)
FONT_BUTTON = (FONT_FAMILY, 13, "bold")
FONT_MONO = (FONT_MONO_FAMILY, 12)

# -- Spacing & shape -------------------------------------------------------
PAD_SM = 6
PAD_MD = 10
PAD_LG = 16

CARD_RADIUS = 12
BUTTON_RADIUS = 8

WINDOW_W = 480
WINDOW_H = 1040
