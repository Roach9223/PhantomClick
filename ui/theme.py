"""Design tokens for the Qt UI.

Single source of truth for color, type, spacing, motion, and radius. Imported
by every widget and by :mod:`ui.qss` for the application stylesheet.

The aesthetic: warm-neutral dark, single coral accent, generous whitespace,
real motion on state changes. Built around an 8 px spacing rhythm so layouts
align without bespoke padding numbers everywhere.
"""

from __future__ import annotations


# -- Surfaces ---------------------------------------------------------------
# Layered grays so cards visibly elevate above the window. Deeper than CTk
# defaults to give the accent more pop. The 2025 redesign nudged BG / SURFACE
# / BORDER a hair to give cards more separation without changing the warmth.
BG = "#0a0c10"            # window
SURFACE = "#14171d"       # primary card
SURFACE_HIGH = "#1c2029"  # entries, second-elevation cards
SURFACE_PRESS = "#222831"
SURFACE_PANEL = "#0e1116" # nested sub-panel inside a card (Realism stub)
BORDER = "#1f242c"        # 1px card borders / dividers
BORDER_STRONG = "#323844"
BORDER_SUBTLE = "#1c2027" # subtler than BORDER, used by nested panels
DIVIDER = "#1d2129"
DIVIDER_PAGE = "#1a1d24"  # very subtle rule under page H1

# -- Accent + semantic colors ----------------------------------------------
# Teal-cyan accent (was coral #ff5470). The Start button stays green, so the
# accent moved to a cooler hue that pairs better with warm-neutral surfaces
# and reads more "tech / gaming" without competing with the green action.
ACCENT = "#22d3ee"
ACCENT_HOVER = "#38e6ff"
ACCENT_PRESSED = "#06b6d4"
# Soft accent wash for backgrounds — rgba string consumed by QSS only.
ACCENT_DIM = "rgba(34, 211, 238, 0.12)"
ACCENT_DIM_FALLBACK = "#0f1d22"  # solid dark teal hex for flat-color properties
ACCENT_TEXT = "#67e8f9"   # lighter cyan text on dim backgrounds (state pills)

START = "#34d399"
START_HOVER = "#4adea8"
# Stop button uses a desaturated red so coral can be reserved for the
# accent role (slider thumbs, focus, tab indicator). A bright Stop button
# next to a bright Start button created visual noise without hierarchy.
STOP_QUIET = "#9e3a4a"
STOP_QUIET_HOVER = "#b54355"
STOP = STOP_QUIET
STOP_HOVER = STOP_QUIET_HOVER

DANGER = "#ef4444"
DANGER_DEEP = "#9a3346"

WARN = "#fbbf24"          # pause/searching
INFO = "#5b8def"          # hover-zone accent / locked tracker

STATUS_ACTIVE = START
STATUS_IDLE = "#71717a"
STATUS_PAUSED = WARN

# -- Text -------------------------------------------------------------------
TEXT_PRIMARY = "#ededed"
TEXT_SECONDARY = "#9ca3af"
TEXT_TERTIARY = "#6b7280"
TEXT_DISABLED = "#52525b"

# -- Typography -------------------------------------------------------------
# Segoe UI Variable ships on Windows 11. Falls back to Segoe UI on Win10.
FONT_FAMILY = "Segoe UI Variable Text, Segoe UI, sans-serif"
FONT_DISPLAY = "Segoe UI Variable Display, Segoe UI, sans-serif"
FONT_MONO = "Cascadia Mono, Consolas, monospace"

# Type scale (px). 6 steps from caption (10) → page hero (28). Body sits at
# 14 — comfortable to read in a dark window without filling the page. Use
# the role attribute on QLabel (role="title|subtitle|body|hint|muted|...") so
# QSS in :mod:`ui.qss` applies the right size + line height + color.
SIZE_XS = 10              # captions, micro-labels
SIZE_SM = 12              # secondary text, helper lines, mono values
SIZE_BODY = 14            # primary reading size — most labels and values
SIZE_LG = 16              # subheaders, section titles inside expanded panes
SIZE_XL = 20              # card titles
SIZE_TITLE = 28           # page hero / brand

# Legacy aliases (gradually migrating callers off these). New code should
# use the SIZE_XS / SIZE_SM / SIZE_BODY / SIZE_LG / SIZE_XL / SIZE_TITLE
# scale and prefer setting role= on QLabel over inline font sizes.
SIZE_HEADER = SIZE_SM
SIZE_VALUE = SIZE_BODY
SIZE_SMALL = SIZE_XS
SIZE_MONO = SIZE_SM
# Section eyebrow (LABEL / TIMING / TARGET) — bumped from XS=10 to 11 so
# the uppercase teal label has enough presence to read as a real
# hierarchy anchor inside step bodies.
SIZE_SECTION_LABEL = 11
# Field labels: 13 px semibold so they sit between body (14) and hint (12)
# without competing with section labels.
SIZE_FIELD_LABEL = 13
SIZE_FIELD_VALUE = SIZE_BODY
SIZE_HINT = SIZE_SM
SIZE_STAT_VALUE = 28
SIZE_KEY_CHIP = SIZE_BODY

# Line heights (CSS-style multipliers; QSS doesn't natively understand
# "line-height" so we derive padding/margin in :mod:`ui.qss`).
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

# In-card vertical rhythm. Single 4-step ladder: card → section → field → row.
# Card padding tightened from 16 → 14 in the redesign; cards now hug content
# instead of leaving dead space, so the smaller padding reads cleaner.
CARD_PAD = 14             # outer padding inside every Card body
# SECTION_GAP decoupled from SP_LG: the step-body redesign needs a real
# breathing room between named sections so the uppercase eyebrows read as
# anchors, not noise. 24 px tracks the 8-grid (3 units).
SECTION_GAP = 24          # between Section groups inside a card
FIELD_GAP = 12            # between fields within a section (8-grid: 1.5 units)
ROW_GAP = SP_SM           # 8 — between micro-rows inside a single field

# Standard control heights — applied across cards for consistency.
INPUT_H = 32             # text inputs, segmented controls
BUTTON_H = 32            # in-card secondary
BUTTON_H_PRIMARY = 36    # in-card primary (Draw, + Add)
BUTTON_H_HERO = 40       # topbar Start / Stop

# -- Radius -----------------------------------------------------------------
# One-notch softer than the previous pass (was 12 / 8 / 6). Reads visibly
# more rounded without crossing into "consumer-app" territory.
RADIUS_CARD = 14
RADIUS_BUTTON = 10
RADIUS_PILL = 9999     # full-round
RADIUS_INPUT = 8

# -- Borders ----------------------------------------------------------------
BORDER_W = 1

# -- Settings-style page tokens (Apple System Settings rhythm) -------------
# A second visual lane introduced for the form-row pages (Hover, Behavior
# follow-up, Hotkeys, Settings, Timers). The Click page keeps its Card-based
# layout; these tokens apply to pages built from GroupHeader + SettingsGroup
# + SettingsRow primitives. Content is left-aligned with a max-width cap so
# wide windows don't sprawl.
PAGE_PAD_X = 36
PAGE_PAD_Y_TOP = 32
PAGE_PAD_Y_BOTTOM = 40
PAGE_CONTENT_MAX_WIDTH = 640

GROUP_BG = SURFACE                # form-row container; same color as Card
GROUP_BORDER = BORDER             # subtle 1px frame
GROUP_RADIUS = 10
GROUP_HAIRLINE = "#1c2027"        # 1px row separator inside a group

GROUP_HEADER_COLOR = "#6b7280"
GROUP_HEADER_PAD_LEFT = 14        # aligns header text with first row's content

ROW_HEIGHT_MIN = 44
ROW_PAD_X = 16
ROW_PAD_Y = 13

# Tinted accent button — quieter than solid teal. The new "primary" action
# style for form pages.
ACCENT_TINT_BG = "rgba(34, 211, 238, 0.12)"
ACCENT_TINT_BG_HOVER = "rgba(34, 211, 238, 0.18)"
ACCENT_TINT_TEXT = "#67e8f9"
ACCENT_TINT_TEXT_HOVER = "#a5f3fc"

FOOTER_HINT_COLOR = "#6b7280"
FOOTER_HINT_LINK = "#67e8f9"

# -- Motion (durations in ms) ----------------------------------------------
DUR_FAST = 140         # hover, micro-interactions
DUR_NORMAL = 220       # state changes, expanders
DUR_SLOW = 360         # sheet transitions, large reveals
DUR_TOAST = 3000       # toast lifetime before fade

# Easing names map to QEasingCurve types in code.
EASE_OUT = "OutCubic"      # default for entrances + state changes
EASE_IN_OUT = "InOutCubic" # for symmetric transitions

# -- Window -----------------------------------------------------------------
# Landscape default for the new shell (NavRail + main + topbar). 1280×800 is
# a comfortable laptop default; min keeps the rail + cards usable.
WINDOW_W_MIN = 960
WINDOW_H_MIN = 600
WINDOW_W_DEFAULT = 1280
WINDOW_H_DEFAULT = 800

# Shell layout constants.
NAV_RAIL_W = 200
TOPBAR_H = 52
# Threshold at which the Click page collapses its two-card row into a stack.
CLICK_PAGE_TWO_COL_MIN = 1200

# -- Zone overlay defaults --------------------------------------------------
ZONE_DEFAULT_COLOR = ACCENT
ZONE_DEFAULT_OPACITY = 0.25
HOVER_DEFAULT_COLOR = INFO
HOVER_DEFAULT_OPACITY = 0.22
