"""Application-wide QSS stylesheet.

QSS is Qt's CSS-equivalent — same selector syntax, slightly different property
set. We build the stylesheet from :mod:`ui.theme` tokens so changing a
color or spacing constant updates every widget that uses it.

Specific widgets (Card, RangeSlider, Toast) ship their own paint logic and
only ride this sheet for typography + base color hooks.
"""

from __future__ import annotations

from . import theme as t


def build_stylesheet() -> str:
    """Return the full app stylesheet as a single string."""
    return f"""
    /* -- Window + base ------------------------------------------------- */
    QMainWindow, QWidget {{
        background: {t.BG};
        color: {t.TEXT_PRIMARY};
        font-family: {t.FONT_FAMILY};
        font-size: {t.SIZE_BODY}px;
    }}

    QLabel {{
        background: transparent;
        color: {t.TEXT_PRIMARY};
        font-size: {t.SIZE_BODY}px;
    }}

    /* Color roles — applied alongside size roles below. */
    QLabel[role="secondary"] {{ color: {t.TEXT_SECONDARY}; }}
    QLabel[role="tertiary"]  {{ color: {t.TEXT_TERTIARY}; }}
    QLabel[role="muted"]     {{ color: {t.TEXT_DISABLED}; }}
    QLabel[role="accent"]    {{ color: {t.ACCENT}; }}
    QLabel[role="warn"]      {{ color: {t.WARN}; }}
    QLabel[role="success"]   {{ color: {t.START}; }}
    QLabel[role="info"]      {{ color: {t.INFO}; }}
    QLabel[role="error"]     {{ color: {t.DANGER}; }}

    /* Size + style roles. role="hint" is the workhorse for helper text;
       role="body" the default reading size; role="subtitle" / "title" for
       hierarchy; role="mono" for values that should read as code. */
    QLabel[role="title"] {{
        font-family: {t.FONT_DISPLAY};
        font-size: {t.SIZE_TITLE}px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QLabel[role="subtitle"] {{
        font-family: {t.FONT_DISPLAY};
        font-size: {t.SIZE_XL}px;
        font-weight: 700;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="section"] {{
        font-size: {t.SIZE_LG}px;
        font-weight: 700;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="body"] {{
        font-size: {t.SIZE_BODY}px;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="hint"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.TEXT_TERTIARY};
        line-height: 140%;
    }}
    QLabel[role="caption"] {{
        font-size: {t.SIZE_XS}px;
        color: {t.TEXT_TERTIARY};
        text-transform: uppercase;
        letter-spacing: 0.6px;
    }}
    /* Eyebrow style — small uppercase title shown atop a card. The
       redesign demoted the card title from "Display 10/700" with heavy
       tracking to a quieter Body 10/500 sans-serif so the page H1 carries
       the visual weight. Cards uppercase + letter-space their text via
       QFont (QSS doesn't support text-transform / letter-spacing). */
    QLabel[role="card-header"] {{
        color: {t.TEXT_SECONDARY};
        font-size: 10px;
        font-weight: 500;
    }}
    QLabel[role="value"], QLabel[role="mono"] {{
        color: {t.TEXT_PRIMARY};
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_SM}px;
    }}
    QLabel[role="status-dot"] {{ font-size: 18px; font-weight: 700; }}

    /* Page header — H1 + subtitle + bottom rule. Lives at the top of every
       page so the user always knows where they are without reading the nav. */
    QFrame#page-header {{
        border: none;
        border-bottom: 1px solid {t.DIVIDER_PAGE};
    }}
    QLabel[role="page-title"] {{
        font-family: {t.FONT_DISPLAY};
        font-size: 22px;
        font-weight: 700;
        color: {t.TEXT_PRIMARY};
        letter-spacing: -0.2px;
    }}
    QLabel[role="page-subtitle"] {{
        font-size: 13px;
        color: {t.TEXT_TERTIARY};
    }}

    /* Section eyebrow — small uppercase label above a group of fields
       inside a card. SectionLabel widget pre-uppercases + sets QFont
       letter-spacing so the visual matches the spec without QSS hacks. */
    QLabel[role="section-label"] {{
        font-size: {t.SIZE_SECTION_LABEL}px;
        font-weight: 500;
        color: {t.ACCENT};
    }}

    /* Card-state pill — sits in the title row to show "Configured" /
       "Not set" / "Drawing…". The accent variant uses a soft coral wash
       (rgba) so the live accent stays vibrant by contrast. */
    QLabel[role="state-pill"] {{
        font-size: 10px;
        font-weight: 500;
        color: {t.ACCENT_TEXT};
        background: {t.ACCENT_DIM};
        padding: 2px 8px;
        border-radius: 9999px;
    }}
    QLabel[role="state-pill"][tone="neutral"] {{
        color: {t.TEXT_SECONDARY};
        background: {t.SURFACE_PANEL};
    }}

    /* Nested panel — inset surface for sub-cards (e.g. Realism stub
       inside the Timing card). Visually marks "this is its own thing,
       not part of the surrounding fields". */
    QFrame[role="panel"] {{
        background: {t.SURFACE_PANEL};
        border: 1px solid {t.BORDER_SUBTLE};
        border-radius: 6px;
    }}

    /* Mono readout — paired number + unit text used by IntervalDisplay.
       Number is large mono, unit is small sans-serif so they read like
       "7.5 s" with intent. */
    QLabel[role="mono-readout"] {{
        font-family: {t.FONT_MONO};
        font-size: 18px;
        font-weight: 500;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="mono-readout-unit"] {{
        font-family: {t.FONT_FAMILY};
        font-size: 11px;
        color: {t.TEXT_TERTIARY};
    }}
    QLabel[role="mono-readout-arrow"] {{
        color: {t.DIVIDER};
        font-size: 14px;
    }}

    /* Preset card — two-line button (name + range) used by TimingCard.
       Replaces the previous pill-shape so presets read as "tap to apply
       this whole timing window" rather than as a chip selector. */
    QPushButton#preset-card {{
        background: transparent;
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 6px;
        padding: 0;
        text-align: left;
    }}
    QPushButton#preset-card:hover {{
        border-color: {t.ACCENT};
    }}
    QPushButton#preset-card:checked {{
        border-color: {t.ACCENT};
    }}
    QPushButton#preset-card QLabel {{
        background: transparent;
    }}

    /* -- Card frames --------------------------------------------------- */
    /* The Card class paints its own background; this sheet only handles
       child layout consistency. */
    QFrame#card {{
        background: {t.SURFACE};
        border: {t.BORDER_W}px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    /* Active-state stripe: cards that represent a running/listening
       service (Monitor when streaming) get a 3 px teal left edge to
       echo the nav-rail and step-card active conventions. */
    QFrame#card[listening="true"] {{
        border-left: 3px solid {t.ACCENT};
    }}
    QFrame#card-inner {{
        background: transparent;
    }}
    QFrame[role="divider"] {{
        background: {t.DIVIDER};
        max-height: 1px;
        min-height: 1px;
    }}

    /* -- Settings-style form pages ------------------------------------- */
    /* Apple System Settings rhythm: uppercase eyebrow above a rounded rect
       that contains stacked rows separated by 1px hairlines. Used by the
       Hover page (and follow-up form pages). */
    QFrame[role="settings-group"] {{
        background: {t.GROUP_BG};
        border: 1px solid {t.GROUP_BORDER};
        border-radius: {t.GROUP_RADIUS}px;
    }}
    /* Active-state stripe: master-switch groups (Behavior tab) get a
       3 px teal left edge when their master is on. Mirrors the
       step-card and Monitor-card active conventions so the visual
       grammar is consistent across mode and form-row pages. */
    QFrame[role="settings-group"][active="true"] {{
        border-left: 3px solid {t.ACCENT};
    }}
    QFrame[role="settings-row"] {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.GROUP_HAIRLINE};
    }}
    QFrame[role="settings-row"][last="true"] {{
        border-bottom: none;
    }}
    QFrame[role="settings-row"] QLabel {{
        background: transparent;
    }}

    QLabel[role="group-header"] {{
        font-size: 11px;
        font-weight: 600;
        color: {t.ACCENT};
    }}
    QLabel[role="row-label"] {{
        font-size: 13px;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="row-desc"] {{
        font-size: 11px;
        color: {t.TEXT_TERTIARY};
    }}

    /* Quiet tinted accent button — the "primary" action on form pages.
       Reads as primary without the loud solid-coral slab. */
    QPushButton[role="quiet-accent"] {{
        background: {t.ACCENT_TINT_BG};
        color: {t.ACCENT_TINT_TEXT};
        border: none;
        padding: 5px 12px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton[role="quiet-accent"]:hover {{
        background: {t.ACCENT_TINT_BG_HOVER};
        color: {t.ACCENT_TINT_TEXT_HOVER};
    }}
    QPushButton[role="quiet-accent"]:disabled {{
        color: {t.TEXT_DISABLED};
    }}

    /* Borderless secondary button — fills only on hover. Used for menu
       triggers and footer links. */
    QPushButton[role="borderless"] {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: none;
        padding: 5px 8px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QPushButton[role="borderless"]:hover {{
        background: {t.SURFACE};
        color: {t.TEXT_PRIMARY};
    }}

    /* Stats value — big mono number on the right of a settings-row.
       Reads as a primary readout while still living in a row. */
    QLabel[role="stat-value"] {{
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_STAT_VALUE}px;
        font-weight: 500;
        color: {t.TEXT_PRIMARY};
    }}

    QLabel[role="footer-hint"] {{
        font-size: 11px;
        color: {t.FOOTER_HINT_COLOR};
    }}
    QLabel[role="footer-hint"] a {{
        color: {t.FOOTER_HINT_LINK};
        text-decoration: none;
    }}

    /* Step rows in the Record tab. The visual differentiation is by FILL
       elevation, not by border — the prior 1px BORDER outline collided
       with the SURFACE_HIGH fill (only ~3 RGB units apart) and read as a
       blocky outline. The active state surfaces an accent stripe on the
       left edge (mirrors the nav rail), with the resting state holding
       the same 3 px indent so toggling doesn't shift the content. */
    QFrame#step-card {{
        background: {t.SURFACE_HIGH};
        border: 0;
        border-left: 3px solid transparent;
        border-radius: 10px;
    }}
    QFrame#step-card[active="true"] {{
        border-left: 3px solid {t.ACCENT};
    }}
    /* Editor target — the step whose body is currently expanded. Same
       3 px teal stripe as ``[active="true"]`` (engine running on this
       step). When both are true they collapse to one stripe — fine. */
    QFrame#step-card[expanded="true"] {{
        border-left: 3px solid {t.ACCENT};
    }}
    /* Hairline divider between a step body's content and its trailing
       Test/Clear action row. Used as ``QFrame[role="row-divider"]``. */
    QFrame[role="row-divider"] {{
        background: {t.DIVIDER};
        border: none;
        max-height: 1px;
        min-height: 1px;
    }}
    QFrame#step-group-header {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.DIVIDER};
    }}

    /* -- Buttons ------------------------------------------------------- */
    QPushButton {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 6px 14px;
        font-weight: 600;
    }}
    QPushButton:hover    {{ background: {t.SURFACE_PRESS}; border-color: {t.BORDER_STRONG}; }}
    QPushButton:pressed  {{ background: {t.BG}; }}
    QPushButton:disabled {{
        background: {t.SURFACE};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    QPushButton[variant="primary"] {{
        background: {t.ACCENT};
        color: #ffffff;
        border: 1px solid {t.ACCENT};
    }}
    QPushButton[variant="primary"]:hover    {{ background: {t.ACCENT_HOVER}; border-color: {t.ACCENT_HOVER}; }}
    QPushButton[variant="primary"]:pressed  {{ background: {t.ACCENT_PRESSED}; }}
    QPushButton[variant="primary"]:disabled {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    QPushButton[variant="success"] {{
        background: {t.START};
        color: #07120c;
        border: 1px solid {t.START};
    }}
    QPushButton[variant="success"]:hover    {{ background: {t.START_HOVER}; }}
    QPushButton[variant="success"]:disabled {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    QPushButton[variant="danger"] {{
        background: {t.STOP};
        color: #ffffff;
        border: 1px solid {t.STOP};
    }}
    QPushButton[variant="danger"]:hover     {{ background: {t.STOP_HOVER}; }}
    QPushButton[variant="danger"]:disabled  {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
    }}
    QPushButton[variant="ghost"]:hover {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER};
    }}

    /* Warn-outline: amber border + amber text. Used for actions whose
       side effect is destructive enough to deserve a visual cue but
       common enough that a confirm dialog would be friction (Monitor's
       "Regenerate token" — invalidates existing phone URLs). Pair with
       a tooltip explaining the consequence. */
    QPushButton[variant="warn-outline"] {{
        background: transparent;
        color: {t.WARN};
        border: 1px solid {t.WARN};
    }}
    QPushButton[variant="warn-outline"]:hover {{
        background: rgba(251, 191, 36, 0.10);
    }}
    QPushButton[variant="warn-outline"]:pressed {{
        background: rgba(251, 191, 36, 0.16);
    }}
    QPushButton[variant="warn-outline"]:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    /* Quiet-primary: neutral surface, accent text, accent border on hover.
       Used for Draw / Add buttons that shouldn't dominate but should be
       discoverable as the actionable element in their card. */
    QPushButton[variant="primary-quiet"] {{
        background: {t.SURFACE_HIGH};
        color: {t.ACCENT};
        border: 1px solid {t.BORDER};
        font-weight: 700;
    }}
    QPushButton[variant="primary-quiet"]:hover {{
        background: {t.ACCENT_DIM};
        border-color: {t.ACCENT};
    }}
    QPushButton[variant="primary-quiet"]:pressed {{
        background: {t.SURFACE_PRESS};
    }}
    QPushButton[variant="primary-quiet"]:disabled {{
        background: {t.SURFACE};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER};
    }}

    QPushButton[variant="pill-accent"] {{
        background: transparent;
        color: {t.ACCENT};
        border: 1px solid {t.ACCENT};
        border-radius: 14px;
        padding: 4px 12px;
        font-size: {t.SIZE_SMALL}px;
        font-weight: 600;
    }}
    QPushButton[variant="pill-accent"]:hover {{
        background: {t.ACCENT_DIM};
    }}

    QPushButton[variant="icon"] {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
        padding: 0;
        min-width: 28px;
        min-height: 24px;
        max-height: 24px;
    }}
    QPushButton[variant="icon"]:hover {{
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER_STRONG};
    }}
    QPushButton[variant="icon-danger"] {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
        padding: 0;
        min-width: 28px;
        min-height: 24px;
        max-height: 24px;
    }}
    QPushButton[variant="icon-danger"]:hover {{
        background: {t.DANGER_DEEP};
        color: #ffffff;
        border-color: {t.DANGER};
    }}

    /* -- Inputs -------------------------------------------------------- */
    /* Inputs sit RECESSED into their parent card — fill = page BG so they
       read as wells dropped into the SURFACE_HIGH step card. The resting
       border is barely visible (BORDER_SUBTLE on dark fill); focus brings
       in the live accent. Removes the prior fill/border collision where
       inputs disappeared into the card they sat inside. */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background: {t.BG};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_SUBTLE};
        border-radius: {t.RADIUS_INPUT}px;
        padding: 4px 8px;
        selection-background-color: {t.ACCENT};
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border: 1px solid {t.ACCENT};
    }}
    QLineEdit[role="value-entry"] {{
        font-family: {t.FONT_MONO};
        color: {t.ACCENT};
        background: {t.BG};
        text-align: center;
    }}
    QLineEdit[role="mono"] {{
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_SM}px;
    }}
    QLineEdit[invalid="true"] {{ color: {t.WARN}; border-color: {t.WARN}; }}

    /* -- CheckBox / RadioButton --------------------------------------- */
    QCheckBox, QRadioButton {{
        color: {t.TEXT_PRIMARY};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t.BORDER_STRONG};
        background: {t.SURFACE_HIGH};
    }}
    QCheckBox::indicator         {{ border-radius: 4px; }}
    QRadioButton::indicator      {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
        border-color: {t.ACCENT};
    }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background: {t.ACCENT};
        border-color: {t.ACCENT};
    }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        background: {t.SURFACE};
        border-color: {t.BORDER};
    }}

    /* -- Native QSlider (ranges use a custom widget) ------------------ */
    QSlider {{
        outline: none;
    }}
    QSlider:focus {{
        outline: none;
    }}
    QSlider::groove:horizontal {{
        height: 4px;
        background: {t.SURFACE_HIGH};
        border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{
        background: {t.ACCENT};
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {t.ACCENT};
        border: none;
        width: 14px;
        height: 14px;
        margin: -6px 0;
        border-radius: 7px;
    }}
    QSlider::handle:horizontal:hover  {{ background: {t.ACCENT_HOVER}; }}
    QSlider::handle:horizontal:pressed {{ background: {t.ACCENT_PRESSED}; }}
    QSlider::handle:horizontal:focus  {{ outline: none; }}
    QSlider:disabled::sub-page:horizontal {{ background: {t.BORDER_STRONG}; }}
    QSlider:disabled::handle:horizontal   {{ background: {t.BORDER_STRONG}; }}

    /* -- ScrollArea / ScrollBar --------------------------------------- */
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.BORDER_STRONG};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t.TEXT_TERTIARY}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    /* -- SegmentedControl --------------------------------------------- */
    /* iOS-style: the frame paints a darker (recessed) track, and the
       active option floats on top with a soft surface-high pill. No
       coral fill — keeps coral reserved for primary actions. */
    QFrame#segmented-frame {{
        background: {t.BG};
        border: none;
        border-radius: 7px;
        padding: 2px;
    }}
    QPushButton#segmented-btn {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: none;
        border-radius: 5px;
        padding: 5px 12px;
        font-size: {t.SIZE_SM}px;
        font-weight: 500;
    }}
    QPushButton#segmented-btn:hover {{
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton#segmented-btn[active="true"] {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton#segmented-btn[active="true"]:hover {{
        background: {t.SURFACE_HIGH};
    }}

    /* -- TopBar + NavRail (shell chrome) ------------------------------
       Transparent so Mica shows through on Win11; on Win10 / Mica-off the
       solid window BG shows behind. Subtle hairline borders mark the
       zone boundaries without painting a heavy bar. */
    QFrame#topbar {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.BORDER};
    }}
    QFrame#nav-rail {{
        background: transparent;
        border: none;
        border-right: 1px solid {t.BORDER};
    }}
    /* NavRail items. The redesign drops the muddy ACCENT_DIM background
       tint that was killing the live accent's vibrancy; the active state
       now uses a soft surface bg + 2px coral left border + primary text.
       The transparent left border on inactive items keeps the text from
       shifting horizontally when the active border appears. */
    QPushButton#nav-item {{
        background: transparent;
        border: none;
        border-left: 2px solid transparent;
        border-radius: {t.RADIUS_INPUT}px;
        text-align: left;
        padding: 0;
        color: {t.TEXT_SECONDARY};
        font-weight: 500;
    }}
    QPushButton#nav-item QLabel {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        font-weight: 500;
    }}
    QPushButton#nav-item:hover {{
        background: {t.SURFACE};
    }}
    QPushButton#nav-item:hover QLabel {{
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton#nav-item[active="true"] {{
        background: {t.SURFACE};
        border-left: 2px solid {t.ACCENT};
        border-top-left-radius: 0;
        border-bottom-left-radius: 0;
    }}
    QPushButton#nav-item[active="true"] QLabel {{
        color: {t.TEXT_PRIMARY};
        font-weight: 600;
    }}

    /* -- ComboBox ----------------------------------------------------- */
    /* Same recessed-well treatment as QLineEdit — fill at page BG so the
       combo reads as inset into its parent card. */
    QComboBox {{
        background: {t.BG};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_SUBTLE};
        border-radius: {t.RADIUS_INPUT}px;
        padding: 4px 10px;
    }}
    QComboBox:hover  {{ border-color: {t.BORDER_STRONG}; }}
    QComboBox:focus  {{ border-color: {t.ACCENT}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        selection-background-color: {t.ACCENT};
        selection-color: #ffffff;
        outline: 0;
    }}

    /* -- Command Palette ---------------------------------------------- */
    QDialog#command-palette {{
        background: transparent;
    }}
    QFrame#palette-frame {{
        background: {t.SURFACE_HIGH};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 12px;
    }}
    QLineEdit#palette-search {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.BORDER};
        border-radius: 0;
        padding: 10px 8px;
        font-family: {t.FONT_DISPLAY};
        font-size: 16px;
        color: {t.TEXT_PRIMARY};
    }}
    QLineEdit#palette-search:focus {{ border-bottom-color: {t.ACCENT}; }}
    QFrame#palette-rows {{ background: transparent; }}
    QFrame#palette-row {{
        background: transparent;
        border-radius: 6px;
    }}
    QFrame#palette-row:hover {{
        background: {t.SURFACE_PRESS};
    }}
    QFrame#palette-row[highlighted="true"] {{
        background: {t.ACCENT_DIM};
    }}

    /* -- ToolTip ------------------------------------------------------- */
    QToolTip {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: {t.SIZE_SMALL}px;
    }}
    """
