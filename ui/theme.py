"""Design tokens for the Qt UI. "Command deck" theme, slate edition.

Single source of truth for color, type, spacing, motion, and radius. Imported
by every widget and by :mod:`ui.qss` for the application stylesheet.

The look: an operations console. Charcoal-slate base (never pure black),
blue-grey panels with a full 1 px border and an 8 px radius, condensed
sans labels over monospace values, and two accents that each mean one
thing:

- ``ACCENT`` (ice blue) is SELECTION and CONTROL: the active mode, the
  selected segment, a focused input, the target monitor, the click zone
  outline, the primary button. It says "this is what you are working on".
- ``RUN`` (green) is LIVE and NOMINAL: the running status, a firing rule,
  a step being executed, a subsystem that reports healthy. It says "this
  is happening right now" or "this is fine".

Red (``STOP``) is stop and fault, amber (``WARN``) is caution. Neither
accent is ever decoration and neither is a heading colour: section
eyebrows and panel headers are ``TEXT_TERTIARY``.

Type: Barlow (``FONT_FAMILY``) carries every label, button, heading and
sentence; JetBrains Mono (``FONT_MONO``) carries values, coordinates,
times, keys and the log. Both ship in ``ui/fonts``.

Motion: state changes are instant. 120 ms is the ceiling for anything
that has to move (the expander). The one exception is the zone map's
sweep, which turns only while the engine runs and exists to report that
it is running; motion is allowed where it carries live state and nowhere
else.

Every name from the lime theme is kept as an alias so existing cards
keep importing without edits.
"""

from __future__ import annotations


# -- Surfaces ---------------------------------------------------------------
BG = "#0E1116"             # window
SURFACE = "#151A21"        # panels / cards
SURFACE_HIGH = "#1B222B"   # raised rows, hover fills, nav active
SURFACE_PRESS = "#222B36"  # pressed / selected cell
SURFACE_PANEL = "#11161C"  # recessed wells: inputs, nested sub-panels

BORDER = "#26303B"         # the 1 px frame on every panel
BORDER_STRONG = "#34414F"  # slider tracks, major ruler ticks, hover borders
BORDER_SUBTLE = "#1E2730"  # disabled borders, hairlines inside wells
DIVIDER = BORDER
DIVIDER_PAGE = BORDER

# -- Accent + semantic colors ----------------------------------------------
# Ice blue: selection, focus, target, primary control.
ACCENT = "#7CC4F2"
ACCENT_HOVER = "#9AD3F7"
ACCENT_PRESSED = "#5FAEE0"
ACCENT_DIM = "rgba(124, 196, 242, 0.12)"   # QSS only
ACCENT_DIM_FALLBACK = "#17283A"            # solid hex for QColor / paint
ACCENT_TEXT = ACCENT

# Green: live, running, nominal.
RUN = "#4ADE80"
RUN_HOVER = "#6EE7A0"
RUN_PRESSED = "#34C46A"
RUN_DIM = "rgba(74, 222, 128, 0.12)"       # QSS only
RUN_DIM_FALLBACK = "#173124"

START = ACCENT
START_HOVER = ACCENT_HOVER
STOP = "#E5484D"
STOP_HOVER = "#C93C41"
STOP_QUIET = "#3B262A"          # danger button resting border
DANGER = STOP
DANGER_DEEP = "#A82A23"

WARN = "#E0A83A"                # caution: paused, searching, unsaved
INFO = "#8C9AA8"                # neutral informational, hover zones

STATUS_ACTIVE = RUN
STATUS_IDLE = "#3B4652"
STATUS_PAUSED = WARN

# -- Text -------------------------------------------------------------------
TEXT_PRIMARY = "#DCE3EA"
TEXT_SECONDARY = "#B4BEC9"
TEXT_TERTIARY = "#7C8894"
TEXT_DISABLED = "#5C6772"
TEXT_MICRO = "#6A7682"          # ruler tick values only
TEXT_ON_ACCENT = BG             # near-black text on an ice-blue fill
TEXT_ON_RUN = BG

# -- Typography -------------------------------------------------------------
# Barlow is the UI face (labels, buttons, headings, prose); JetBrains Mono
# is the value face (numbers, coordinates, times, keys, the log). Both
# ship in ui/fonts/ and are registered at startup (main.py); the fallbacks
# cover a missing font file.
FONT_FAMILY = "Barlow, Segoe UI Variable Text, Segoe UI, sans-serif"
FONT_DISPLAY = "Barlow, Segoe UI Variable Display, Segoe UI, sans-serif"
FONT_MONO = "JetBrains Mono, Cascadia Mono, Consolas, monospace"
FONT_LABEL = FONT_FAMILY

# Type scale (px, whole numbers only: Qt's stylesheet parser drops a
# fractional ``font-size``). Body sits at 13; uppercase labels are 12 with
# LABEL_TRACKING letter-spacing. The app font is registered in main.py
# with full hinting so stems snap to the pixel grid on a 100 % monitor;
# nothing goes under SIZE_XS.
SIZE_XS = 10               # ruler ticks, micro captions
SIZE_SM = 12               # uppercase labels, hints
SIZE_BODY = 13             # body
SIZE_CONTROL = 13          # button and segment captions, row labels
SIZE_LG = 14               # readouts, row titles that need weight
SIZE_XL = 18               # large readouts
SIZE_TITLE = 22            # wordmark (Barlow 700)

LABEL_TRACKING = 1.2       # px letter-spacing on uppercase micro-labels
CONTROL_TRACKING = 0.8     # px letter-spacing on button / segment captions
PANEL_HEADER_TRACKING = 1.6
SIZE_PANEL_HEADER = 12     # panel header label, uppercase 600
FONT_WEIGHT_BODY = 500     # Medium
FONT_WEIGHT_LABEL = 600    # SemiBold: uppercase labels and buttons

# Legacy aliases. New code should use the scale above.
SIZE_HEADER = SIZE_SM
SIZE_VALUE = SIZE_BODY
SIZE_SMALL = SIZE_XS
SIZE_MONO = SIZE_BODY
SIZE_SECTION_LABEL = SIZE_SM
SIZE_FIELD_LABEL = SIZE_SM
SIZE_FIELD_VALUE = SIZE_BODY
SIZE_HINT = SIZE_SM
SIZE_STAT_VALUE = 22
SIZE_KEY_CHIP = SIZE_BODY

LINE_TIGHT = 1.2
LINE_NORMAL = 1.45
LINE_RELAXED = 1.6

# -- Spacing (8 px rhythm) -------------------------------------------------
SP_XS = 4
SP_SM = 8
SP_MD = 12
SP_LG = 16
SP_XL = 24
SP_XXL = 32

CARD_PAD = 12
SECTION_GAP = 20
FIELD_GAP = 12
ROW_GAP = SP_SM

# Standard control heights.
INPUT_H = 30
BUTTON_H = 30
BUTTON_H_PRIMARY = 30
BUTTON_H_HERO = 32
ICON_BUTTON = 30           # square icon buttons

# -- Radius -----------------------------------------------------------------
# No full-round pills anywhere. Chips share the button radius.
RADIUS_CARD = 8
RADIUS_BUTTON = 6
RADIUS_INPUT = 6
RADIUS_PILL = 6

# -- Borders ----------------------------------------------------------------
BORDER_W = 1

# -- Form-row page tokens ---------------------------------------------------
PAGE_PAD_X = 32
PAGE_PAD_Y_TOP = 24
PAGE_PAD_Y_BOTTOM = 32
PAGE_CONTENT_MAX_WIDTH = 640

GROUP_BG = SURFACE
GROUP_BORDER = BORDER
GROUP_RADIUS = RADIUS_CARD
GROUP_HAIRLINE = BORDER

GROUP_HEADER_COLOR = TEXT_TERTIARY
GROUP_HEADER_PAD_LEFT = 12

ROW_HEIGHT_MIN = 40
ROW_PAD_X = 12
ROW_PAD_Y = 10

# Tinted accent button (form pages). Ice wash, ice text.
ACCENT_TINT_BG = ACCENT_DIM
ACCENT_TINT_BG_HOVER = "rgba(124, 196, 242, 0.18)"
ACCENT_TINT_TEXT = ACCENT
ACCENT_TINT_TEXT_HOVER = ACCENT_HOVER

FOOTER_HINT_COLOR = TEXT_TERTIARY
FOOTER_HINT_LINK = TEXT_SECONDARY

# -- Motion (durations in ms) ----------------------------------------------
# The deck changes state instantly. 120 ms is the ceiling for anything that
# has to move (expander height). Linear easing, no bounce, no overshoot.
# The zone map sweep is the documented exception (see module docstring).
DUR_FAST = 0
DUR_NORMAL = 120
DUR_SLOW = 120
DUR_TOAST = 3000
SWEEP_PERIOD_MS = 4000     # one full turn of the zone-map sweep

EASE_OUT = "Linear"
EASE_IN_OUT = "Linear"

# -- Window -----------------------------------------------------------------
WINDOW_W_MIN = 960
WINDOW_H_MIN = 600
WINDOW_W_DEFAULT = 1280
WINDOW_H_DEFAULT = 800

NAV_RAIL_W = 200
TOPBAR_H = 52
CLICK_PAGE_TWO_COL_MIN = 1200

# -- Zone overlay defaults --------------------------------------------------
ZONE_DEFAULT_COLOR = ACCENT
ZONE_DEFAULT_OPACITY = 0.25
HOVER_DEFAULT_COLOR = INFO
HOVER_DEFAULT_OPACITY = 0.22
