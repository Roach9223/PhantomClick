"""Design tokens for the Qt UI. "Command deck" theme.

Single source of truth for color, type, spacing, motion, and radius. Imported
by every widget and by :mod:`ui.qss` for the application stylesheet.

The look: mission control. Near-black base, rounded 8 px panels with full
1 px borders, monospace type everywhere except the wordmark, and one lime
accent that only ever means live / armed / selected. Red is stop and fault,
amber is caution. State changes are instant; nothing animates longer than
120 ms. No glow, no gradients, no emoji.

Every name from the previous teal theme is kept as an alias so existing
cards keep importing without edits.
"""

from __future__ import annotations


# -- Surfaces ---------------------------------------------------------------
BG = "#0B0D0C"             # window
SURFACE = "#111413"        # panels / cards
SURFACE_HIGH = "#161A18"   # raised rows, hover fills, nav active
SURFACE_PRESS = "#1C2220"  # pressed / selected cell
SURFACE_PANEL = "#0E100F"  # recessed wells: inputs, nested sub-panels

BORDER = "#1F2422"         # the 1 px frame on every panel
BORDER_STRONG = "#2A2F2C"  # slider tracks, major ruler ticks, hover borders
BORDER_SUBTLE = "#1A1E1C"  # disabled borders, hairlines inside wells
DIVIDER = "#1F2422"
DIVIDER_PAGE = "#1F2422"

# -- Accent + semantic colors ----------------------------------------------
# Lime is the only accent and it encodes STATE: live, armed, selected,
# focused. Never use it for decoration or for a section heading.
ACCENT = "#9BE15D"
ACCENT_HOVER = "#B5EA84"
ACCENT_PRESSED = "#7FC745"
ACCENT_DIM = "rgba(155, 225, 93, 0.10)"   # QSS only
ACCENT_DIM_FALLBACK = "#18251A"            # solid hex for QColor / paint
ACCENT_TEXT = "#9BE15D"

START = ACCENT
START_HOVER = ACCENT_HOVER
STOP = "#E5484D"
STOP_HOVER = "#C93C41"
STOP_QUIET = "#3A2422"          # danger button resting border
DANGER = "#E5484D"
DANGER_DEEP = "#A82A23"

WARN = "#E0A83A"                # caution: paused, searching, unsaved
INFO = "#9A9C95"                # neutral informational, hover zones

STATUS_ACTIVE = ACCENT
STATUS_IDLE = "#3A3F3C"
STATUS_PAUSED = WARN

# -- Text -------------------------------------------------------------------
TEXT_PRIMARY = "#E6E4DF"
TEXT_SECONDARY = "#C9C8C2"
TEXT_TERTIARY = "#8A8D87"
TEXT_DISABLED = "#6B6E68"
TEXT_MICRO = "#6B6E68"          # ruler tick values only
TEXT_ON_ACCENT = BG             # near-black text on a lime fill

# -- Typography -------------------------------------------------------------
# JetBrains Mono ships in ui/fonts/ and is registered at startup (main.py);
# the fallbacks cover a missing font file. Barlow is the wordmark only.
FONT_FAMILY = "JetBrains Mono, Cascadia Mono, Consolas, monospace"
FONT_DISPLAY = "Barlow, Segoe UI Variable Display, Segoe UI, sans-serif"
FONT_MONO = FONT_FAMILY

# Type scale (px, whole numbers only: Qt's stylesheet parser drops a
# fractional ``font-size``). Mono body sits at 13; labels are uppercase 11
# with LABEL_TRACKING letter-spacing. The app font is registered in
# main.py with full hinting so stems snap to the pixel grid on a 100 %
# monitor; sizes below 12 px still read soft there, so nothing goes
# under SIZE_XS.
SIZE_XS = 10               # ruler ticks, micro captions
SIZE_SM = 11               # uppercase labels, hints
SIZE_BODY = 13             # mono body
SIZE_CONTROL = 12          # button and segment captions, row labels
SIZE_LG = 14               # readouts, row titles that need weight
SIZE_XL = 18               # large readouts
SIZE_TITLE = 22            # wordmark (Barlow 700)

LABEL_TRACKING = 1.2       # px letter-spacing on uppercase micro-labels
CONTROL_TRACKING = 0.6     # px letter-spacing on button / segment captions
PANEL_HEADER_TRACKING = 1.6
SIZE_PANEL_HEADER = 11     # panel header label, uppercase 600
FONT_WEIGHT_BODY = 500     # Medium: crisper than Regular at 13 px on 100 %

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

# Tinted accent button (form pages). Lime wash, lime text.
ACCENT_TINT_BG = ACCENT_DIM
ACCENT_TINT_BG_HOVER = "rgba(155, 225, 93, 0.16)"
ACCENT_TINT_TEXT = ACCENT
ACCENT_TINT_TEXT_HOVER = ACCENT_HOVER

FOOTER_HINT_COLOR = TEXT_TERTIARY
FOOTER_HINT_LINK = TEXT_SECONDARY

# -- Motion (durations in ms) ----------------------------------------------
# The deck changes state instantly. 120 ms is the ceiling for anything that
# has to move (expander height). Linear easing, no bounce, no overshoot.
DUR_FAST = 0
DUR_NORMAL = 120
DUR_SLOW = 120
DUR_TOAST = 3000

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
