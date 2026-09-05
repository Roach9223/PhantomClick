"""Application-wide QSS stylesheet for the command deck.

QSS is Qt's CSS-equivalent: same selector syntax, a smaller property set.
The sheet is built from :mod:`ui.theme` tokens so a token change updates
every widget that rides it.

Rules of the deck, enforced here:

- Every panel has a full 1 px BORDER and an 8 px radius. No shadows.
- Monospace everywhere. Barlow appears only on the wordmark
  (``role="title"``).
- Lime (ACCENT) means live / armed / selected / focused. Section eyebrows
  and group headers are TEXT_TERTIARY, never lime.
- Red is stop and fault, amber is caution.
- Nothing here animates; state flips are instant.

Custom-painted widgets (RangeSlider, IOSSwitch, StatusDot, Toast) read the
same tokens directly and only ride this sheet for typography.
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
        font-weight: {t.FONT_WEIGHT_BODY};
    }}

    QLabel {{
        background: transparent;
        color: {t.TEXT_PRIMARY};
        font-size: {t.SIZE_BODY}px;
    }}

    /* Color roles. */
    QLabel[role="secondary"] {{ color: {t.TEXT_SECONDARY}; }}
    QLabel[role="tertiary"]  {{ color: {t.TEXT_TERTIARY}; }}
    QLabel[role="muted"]     {{ color: {t.TEXT_DISABLED}; }}
    QLabel[role="accent"]    {{ color: {t.ACCENT}; }}
    QLabel[role="warn"]      {{ color: {t.WARN}; }}
    QLabel[role="success"]   {{ color: {t.START}; }}
    QLabel[role="info"]      {{ color: {t.INFO}; }}
    QLabel[role="error"]     {{ color: {t.DANGER}; }}

    /* Size + style roles. */
    QLabel[role="title"] {{
        font-family: {t.FONT_DISPLAY};
        font-size: {t.SIZE_TITLE}px;
        font-weight: 700;
        letter-spacing: 0.5px;
    }}
    QLabel[role="subtitle"] {{
        font-size: {t.SIZE_XL}px;
        font-weight: 600;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="section"] {{
        font-size: {t.SIZE_LG}px;
        font-weight: 600;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="body"] {{
        font-size: {t.SIZE_BODY}px;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="hint"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.TEXT_TERTIARY};
    }}
    QLabel[role="caption"] {{
        font-size: {t.SIZE_XS}px;
        color: {t.TEXT_TERTIARY};
        letter-spacing: {t.LABEL_TRACKING}px;
    }}
    /* Panel header label: uppercase 11 px mono, 600, tracked. The Card
       widget pre-uppercases the text and sets QFont letter-spacing. */
    QLabel[role="card-header"] {{
        color: {t.TEXT_PRIMARY};
        font-size: {t.SIZE_PANEL_HEADER}px;
        font-weight: 600;
        letter-spacing: {t.PANEL_HEADER_TRACKING}px;
    }}
    QLabel[role="value"], QLabel[role="mono"] {{
        color: {t.TEXT_PRIMARY};
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_BODY}px;
    }}
    QLabel[role="status-dot"] {{ font-size: 14px; font-weight: 700; }}

    /* Page header. */
    QFrame#page-header {{
        border: none;
        border-bottom: 1px solid {t.DIVIDER_PAGE};
    }}
    QLabel[role="page-title"] {{
        font-size: {t.SIZE_XL}px;
        font-weight: 600;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="page-subtitle"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.TEXT_TERTIARY};
    }}

    /* Section eyebrow: uppercase 10.5 px mono, tertiary. Lime is reserved
       for state, so a heading never gets it. */
    QLabel[role="section-label"] {{
        font-size: {t.SIZE_CONTROL}px;
        font-weight: 600;
        color: {t.TEXT_TERTIARY};
        letter-spacing: {t.LABEL_TRACKING}px;
    }}

    /* Card-state chip in a title row: "Configured" / "Not set". Rectangular
       6 px radius; lime text only for the accent tone (something is set
       or live). */
    QLabel[role="state-pill"] {{
        font-size: {t.SIZE_SM}px;
        font-weight: 600;
        color: {t.ACCENT_TEXT};
        background: {t.ACCENT_DIM};
        border: 1px solid {t.BORDER};
        padding: 2px 8px;
        border-radius: {t.RADIUS_PILL}px;
        letter-spacing: {t.LABEL_TRACKING}px;
    }}
    QLabel[role="state-pill"][tone="neutral"] {{
        color: {t.TEXT_SECONDARY};
        background: {t.SURFACE_PANEL};
    }}

    /* Nested panel: recessed sub-panel inside a card. */
    QFrame[role="panel"] {{
        background: {t.SURFACE_PANEL};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_INPUT}px;
    }}

    /* Mono readout (IntervalDisplay). */
    QLabel[role="mono-readout"] {{
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_XL}px;
        font-weight: 500;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="mono-readout-unit"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.TEXT_TERTIARY};
    }}
    QLabel[role="mono-readout-arrow"] {{
        color: {t.TEXT_TERTIARY};
        font-size: {t.SIZE_BODY}px;
    }}

    /* Preset card: two-line button in TimingCard. Selected = lime border. */
    QPushButton#preset-card {{
        background: {t.SURFACE_PANEL};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 0;
        text-align: left;
    }}
    QPushButton#preset-card:hover {{
        border-color: {t.BORDER_STRONG};
    }}
    QPushButton#preset-card:checked {{
        background: {t.SURFACE_PRESS};
        border-color: {t.ACCENT};
    }}
    QPushButton#preset-card QLabel {{
        background: transparent;
    }}

    /* -- Card frames --------------------------------------------------- */
    QFrame#card {{
        background: {t.SURFACE};
        border: {t.BORDER_W}px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    /* Live-state stripe: a card representing a running service (Monitor
       when streaming) gets a 2 px lime left rule. */
    QFrame#card[listening="true"] {{
        border-left: 2px solid {t.ACCENT};
    }}
    QFrame#card-inner {{
        background: transparent;
    }}
    QFrame[role="divider"] {{
        background: {t.DIVIDER};
        max-height: 1px;
        min-height: 1px;
    }}

    /* -- Form-row pages ------------------------------------------------- */
    QFrame[role="settings-group"] {{
        background: {t.GROUP_BG};
        border: 1px solid {t.GROUP_BORDER};
        border-radius: {t.GROUP_RADIUS}px;
    }}
    QFrame[role="settings-group"][active="true"] {{
        border-left: 2px solid {t.ACCENT};
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
        font-size: {t.SIZE_SM}px;
        font-weight: 600;
        color: {t.GROUP_HEADER_COLOR};
        letter-spacing: {t.LABEL_TRACKING}px;
    }}
    QLabel[role="row-label"] {{
        font-size: {t.SIZE_BODY}px;
        color: {t.TEXT_PRIMARY};
    }}
    QLabel[role="row-desc"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.TEXT_TERTIARY};
    }}

    /* Quiet tinted lime button (form pages). */
    QPushButton[role="quiet-accent"] {{
        background: {t.ACCENT_TINT_BG};
        color: {t.ACCENT_TINT_TEXT};
        border: 1px solid {t.BORDER};
        padding: 4px 12px;
        border-radius: {t.RADIUS_BUTTON}px;
        font-size: {t.SIZE_SM}px;
        font-weight: 600;
        letter-spacing: 1px;
    }}
    QPushButton[role="quiet-accent"]:hover {{
        background: {t.ACCENT_TINT_BG_HOVER};
        color: {t.ACCENT_TINT_TEXT_HOVER};
        border-color: {t.ACCENT};
    }}
    QPushButton[role="quiet-accent"]:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    /* Borderless secondary button; border appears on hover. */
    QPushButton[role="borderless"] {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
        padding: 4px 8px;
        border-radius: {t.RADIUS_BUTTON}px;
        font-size: {t.SIZE_SM}px;
    }}
    QPushButton[role="borderless"]:hover {{
        border-color: {t.BORDER};
        color: {t.TEXT_PRIMARY};
    }}

    /* Stats value: big mono readout on the right of a row. */
    QLabel[role="stat-value"] {{
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_STAT_VALUE}px;
        font-weight: 500;
        color: {t.TEXT_PRIMARY};
    }}

    QLabel[role="footer-hint"] {{
        font-size: {t.SIZE_SM}px;
        color: {t.FOOTER_HINT_COLOR};
    }}
    QLabel[role="footer-hint"] a {{
        color: {t.FOOTER_HINT_LINK};
        text-decoration: none;
    }}

    /* Step rows in Record. Full 1 px border like every other panel; the
       resting left border is BORDER so toggling the active rule does not
       shift content. Active / expanded = 2 px lime left rule. */
    QFrame#step-card {{
        background: {t.SURFACE_HIGH};
        border: 1px solid {t.BORDER};
        border-left: 2px solid {t.BORDER};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QFrame#step-card[active="true"] {{
        border-left: 2px solid {t.ACCENT};
    }}
    QFrame#step-card[expanded="true"] {{
        border-left: 2px solid {t.ACCENT};
    }}
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
    /* Default = secondary: SURFACE_PANEL fill, BORDER, secondary text.
       Uppercase 10.5 px mono with 1 px tracking. No shadows anywhere. */
    QPushButton {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 5px 12px;
        min-height: {t.BUTTON_H - 12}px;
        font-size: {t.SIZE_CONTROL}px;
        font-weight: 600;
        letter-spacing: {t.CONTROL_TRACKING}px;
    }}
    QPushButton:hover    {{ background: {t.SURFACE_HIGH}; border-color: {t.BORDER_STRONG}; color: {t.TEXT_PRIMARY}; }}
    QPushButton:pressed  {{ background: {t.SURFACE_PRESS}; }}
    QPushButton:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}
    QPushButton[variant="secondary"] {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
    }}

    /* Primary / success: lime fill, near-black text. */
    QPushButton[variant="primary"], QPushButton[variant="success"] {{
        background: {t.ACCENT};
        color: {t.TEXT_ON_ACCENT};
        border: 1px solid {t.ACCENT};
        font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover, QPushButton[variant="success"]:hover {{
        background: {t.ACCENT_HOVER};
        border-color: {t.ACCENT_HOVER};
        color: {t.TEXT_ON_ACCENT};
    }}
    QPushButton[variant="primary"]:pressed, QPushButton[variant="success"]:pressed {{
        background: {t.ACCENT_PRESSED};
        border-color: {t.ACCENT_PRESSED};
    }}
    QPushButton[variant="primary"]:disabled, QPushButton[variant="success"]:disabled {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    /* Danger: transparent, dark-red border, red text. Hover fills deep
       red with bone text. */
    QPushButton[variant="danger"] {{
        background: transparent;
        color: {t.DANGER};
        border: 1px solid {t.STOP_QUIET};
    }}
    QPushButton[variant="danger"]:hover {{
        background: {t.DANGER_DEEP};
        color: {t.TEXT_PRIMARY};
        border-color: {t.DANGER_DEEP};
    }}
    QPushButton[variant="danger"]:pressed {{
        background: {t.STOP};
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton[variant="danger"]:disabled {{
        background: transparent;
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    /* Ghost: transparent, border only on hover. */
    QPushButton[variant="ghost"] {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
    }}
    QPushButton[variant="ghost"]:hover {{
        background: transparent;
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER};
    }}

    /* Warn-outline: amber text and border. Pair with a tooltip. */
    QPushButton[variant="warn-outline"] {{
        background: transparent;
        color: {t.WARN};
        border: 1px solid {t.WARN};
    }}
    QPushButton[variant="warn-outline"]:hover {{
        background: rgba(224, 168, 58, 0.10);
        color: {t.WARN};
        border-color: {t.WARN};
    }}
    QPushButton[variant="warn-outline"]:pressed {{
        background: rgba(224, 168, 58, 0.16);
    }}
    QPushButton[variant="warn-outline"]:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    /* Primary-quiet: panel fill, lime text, lime border on hover. Kept for
       Draw / Add buttons that should read as the actionable element. */
    QPushButton[variant="primary-quiet"] {{
        background: {t.SURFACE_PANEL};
        color: {t.ACCENT};
        border: 1px solid {t.BORDER};
    }}
    QPushButton[variant="primary-quiet"]:hover {{
        background: {t.ACCENT_DIM};
        border-color: {t.ACCENT};
        color: {t.ACCENT};
    }}
    QPushButton[variant="primary-quiet"]:pressed {{
        background: {t.SURFACE_PRESS};
    }}
    QPushButton[variant="primary-quiet"]:disabled {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    /* pill-accent: legacy name, now a rectangular lime-outline chip. */
    QPushButton[variant="pill-accent"] {{
        background: transparent;
        color: {t.ACCENT};
        border: 1px solid {t.ACCENT};
        border-radius: {t.RADIUS_PILL}px;
        padding: 3px 10px;
        font-size: {t.SIZE_SM}px;
        font-weight: 600;
    }}
    QPushButton[variant="pill-accent"]:hover {{
        background: {t.ACCENT_DIM};
    }}

    /* Icon buttons: 30 x 30, BORDER, RADIUS_BUTTON. */
    QPushButton[variant="icon"], QPushButton[variant="icon-danger"] {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_SECONDARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 0;
        min-width: {t.ICON_BUTTON}px;
        min-height: {t.ICON_BUTTON}px;
        max-width: {t.ICON_BUTTON}px;
        max-height: {t.ICON_BUTTON}px;
    }}
    QPushButton[variant="icon"]:hover {{
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER_STRONG};
        background: {t.SURFACE_HIGH};
    }}
    QPushButton[variant="icon-danger"]:hover {{
        background: {t.DANGER_DEEP};
        color: {t.TEXT_PRIMARY};
        border-color: {t.DANGER_DEEP};
    }}
    QPushButton[variant="icon"]:disabled, QPushButton[variant="icon-danger"]:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}

    QToolButton {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: 1px solid transparent;
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 2px;
    }}
    QToolButton:hover {{
        color: {t.TEXT_PRIMARY};
        border-color: {t.BORDER};
    }}

    /* -- Inputs -------------------------------------------------------- */
    /* Recessed wells: SURFACE_PANEL fill, 1 px BORDER, mono text. Focus
       border is lime, error border is red. */
    QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_INPUT}px;
        padding: 3px 8px;
        min-height: {t.INPUT_H - 8}px;
        font-family: {t.FONT_MONO};
        selection-background-color: {t.ACCENT};
        selection-color: {t.TEXT_ON_ACCENT};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {t.BORDER_STRONG};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid {t.ACCENT};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {t.TEXT_DISABLED};
        border-color: {t.BORDER_SUBTLE};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button,
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        width: 14px;
        border: none;
        background: transparent;
    }}
    QLineEdit[role="value-entry"] {{
        color: {t.ACCENT};
        text-align: center;
    }}
    QLineEdit[role="mono"] {{
        font-size: {t.SIZE_BODY}px;
    }}
    QLineEdit[invalid="true"], QLineEdit[error="true"],
    QSpinBox[error="true"], QDoubleSpinBox[error="true"] {{
        color: {t.DANGER};
        border-color: {t.DANGER};
    }}

    /* -- CheckBox / RadioButton --------------------------------------- */
    /* Checkboxes render as a 30 x 14 rectangular switch: BORDER frame,
       12 x 10 square knob. Knob is lime when on, STATUS_IDLE when off.
       The knob jumps; there is no animation. */
    QCheckBox, QRadioButton {{
        color: {t.TEXT_PRIMARY};
        spacing: 8px;
        background: transparent;
    }}
    QCheckBox::indicator {{
        width: 28px;
        height: 12px;
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        background: {t.SURFACE_PANEL};
        image: url({_switch_uri(False)});
    }}
    QCheckBox::indicator:hover {{
        border-color: {t.BORDER_STRONG};
    }}
    QCheckBox::indicator:checked {{
        image: url({_switch_uri(True)});
    }}
    QCheckBox::indicator:disabled {{
        border-color: {t.BORDER_SUBTLE};
        image: url({_switch_uri(None)});
    }}
    QRadioButton::indicator {{
        width: 12px;
        height: 12px;
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 6px;
        background: {t.SURFACE_PANEL};
    }}
    QRadioButton::indicator:checked {{
        background: {t.ACCENT};
        border-color: {t.ACCENT};
    }}

    /* -- Native QSlider -------------------------------------------------- */
    /* 1 px track, 3 px lime fill, 10 px round knob. */
    QSlider {{ outline: none; background: transparent; }}
    QSlider:focus {{ outline: none; }}
    QSlider::groove:horizontal {{
        height: 1px;
        background: {t.BORDER_STRONG};
        margin: 0;
    }}
    QSlider::sub-page:horizontal {{
        height: 3px;
        margin: -1px 0;
        background: {t.ACCENT};
    }}
    QSlider::add-page:horizontal {{
        background: transparent;
    }}
    QSlider::handle:horizontal {{
        background: {t.ACCENT};
        border: none;
        width: 10px;
        height: 10px;
        margin: -5px 0;
        border-radius: 5px;
    }}
    QSlider::handle:horizontal:hover  {{ background: {t.ACCENT_HOVER}; }}
    QSlider::handle:horizontal:pressed {{ background: {t.ACCENT_PRESSED}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {t.TEXT_DISABLED}; }}
    QSlider::handle:horizontal:disabled   {{ background: {t.TEXT_DISABLED}; }}

    /* Vertical sliders (control deck): same parts rotated. Qt fills the
       sub-page from the minimum end, which is the bottom for a vertical
       slider, so it reads as a rising level. */
    QSlider::groove:vertical {{
        width: 1px;
        background: {t.BORDER_STRONG};
        margin: 0 10px;
    }}
    QSlider::sub-page:vertical {{
        width: 3px;
        background: {t.ACCENT};
        margin: 0 9px;
    }}
    QSlider::add-page:vertical {{
        background: transparent;
    }}
    QSlider::handle:vertical {{
        height: 10px;
        width: 10px;
        margin: 0 -5px;
        border-radius: 5px;
        background: {t.ACCENT};
        border: none;
    }}
    QSlider::handle:vertical:hover  {{ background: {t.ACCENT_HOVER}; }}
    QSlider::handle:vertical:pressed {{ background: {t.ACCENT_PRESSED}; }}
    QSlider::sub-page:vertical:disabled {{ background: {t.TEXT_DISABLED}; }}
    QSlider::handle:vertical:disabled   {{ background: {t.TEXT_DISABLED}; }}

    /* -- ScrollArea / ScrollBar --------------------------------------- */
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {t.BORDER_STRONG};
        border-radius: 2px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {t.TEXT_TERTIARY}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {t.BORDER_STRONG};
        border-radius: 2px;
        min-width: 30px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; background: transparent;
    }}

    /* -- SegmentedControl --------------------------------------------- */
    /* Connected cells with 1 px dividers. 6 px radius on the group only.
       Selected cell: SURFACE_PRESS with a 2 px lime rule on the top edge
       (horizontal) or the left edge (vertical). */
    QFrame#segmented-frame {{
        background: {t.SURFACE_PANEL};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 0;
    }}
    QPushButton#segmented-btn {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        border: none;
        border-left: 1px solid {t.BORDER};
        border-top: 2px solid transparent;
        border-radius: 0;
        padding: 4px 12px;
        font-size: {t.SIZE_CONTROL}px;
        font-weight: 600;
        letter-spacing: {t.CONTROL_TRACKING}px;
    }}
    QPushButton#segmented-btn[first="true"] {{
        border-left: none;
    }}
    QPushButton#segmented-btn:hover {{
        color: {t.TEXT_PRIMARY};
        background: {t.SURFACE_HIGH};
    }}
    QPushButton#segmented-btn[active="true"] {{
        background: {t.SURFACE_PRESS};
        color: {t.TEXT_PRIMARY};
        border-top: 2px solid {t.ACCENT};
    }}
    QPushButton#segmented-btn[active="true"]:hover {{
        background: {t.SURFACE_PRESS};
    }}
    /* Vertical stacks: divider on top, rule on the left. */
    QPushButton#segmented-btn[orientation="vertical"] {{
        border-left: 2px solid transparent;
        border-top: 1px solid {t.BORDER};
        text-align: left;
    }}
    QPushButton#segmented-btn[orientation="vertical"][first="true"] {{
        border-top: none;
    }}
    QPushButton#segmented-btn[orientation="vertical"][active="true"] {{
        border-left: 2px solid {t.ACCENT};
        border-top: 1px solid {t.BORDER};
    }}
    QPushButton#segmented-btn[orientation="vertical"][active="true"][first="true"] {{
        border-top: none;
    }}

    /* -- TopBar + NavRail (shell chrome) ------------------------------ */
    QFrame#topbar {{
        background: {t.BG};
        border: none;
        border-bottom: 1px solid {t.BORDER};
    }}
    QFrame#nav-rail {{
        background: {t.BG};
        border: none;
        border-right: 1px solid {t.BORDER};
    }}
    /* Nav items: active = SURFACE_HIGH fill, 2 px lime left rule, primary
       text. Idle = secondary text. The transparent left border on idle
       items keeps text from shifting when the rule appears. */
    QPushButton#nav-item {{
        background: transparent;
        border: none;
        border-left: 2px solid transparent;
        border-radius: 0;
        text-align: left;
        padding: 0;
        color: {t.TEXT_SECONDARY};
        font-weight: 500;
        letter-spacing: 0;
    }}
    QPushButton#nav-item QLabel {{
        background: transparent;
        color: {t.TEXT_SECONDARY};
        font-size: {t.SIZE_SM}px;
        font-weight: 600;
        letter-spacing: {t.LABEL_TRACKING}px;
    }}
    QPushButton#nav-item:hover {{
        background: {t.SURFACE};
    }}
    QPushButton#nav-item:hover QLabel {{
        color: {t.TEXT_PRIMARY};
    }}
    QPushButton#nav-item[active="true"] {{
        background: {t.SURFACE_HIGH};
        border-left: 2px solid {t.ACCENT};
    }}
    QPushButton#nav-item[active="true"] QLabel {{
        color: {t.TEXT_PRIMARY};
    }}

    /* -- ComboBox ----------------------------------------------------- */
    QComboBox {{
        background: {t.SURFACE_PANEL};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER};
        border-radius: {t.RADIUS_INPUT}px;
        padding: 3px 10px;
        min-height: {t.INPUT_H - 8}px;
        font-family: {t.FONT_MONO};
    }}
    QComboBox:hover  {{ border-color: {t.BORDER_STRONG}; }}
    QComboBox:focus, QComboBox:on {{ border-color: {t.ACCENT}; }}
    QComboBox:disabled {{ color: {t.TEXT_DISABLED}; border-color: {t.BORDER_SUBTLE}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox::down-arrow {{
        image: url({_chevron_uri()});
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: 0;
        selection-background-color: {t.SURFACE_PRESS};
        selection-color: {t.ACCENT};
        outline: 0;
        padding: 2px;
    }}

    /* -- Menus ---------------------------------------------------------- */
    QMenu {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 5px 14px;
        border-radius: 4px;
    }}
    QMenu::item:selected {{
        background: {t.SURFACE_PRESS};
        color: {t.ACCENT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {t.BORDER};
        margin: 4px 6px;
    }}

    /* -- Command Palette ---------------------------------------------- */
    QDialog#command-palette {{
        background: transparent;
    }}
    QFrame#palette-frame {{
        background: {t.SURFACE};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: {t.RADIUS_CARD}px;
    }}
    QLineEdit#palette-search {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {t.BORDER};
        border-radius: 0;
        padding: 10px 8px;
        font-size: {t.SIZE_LG}px;
        color: {t.TEXT_PRIMARY};
    }}
    QLineEdit#palette-search:focus {{ border-bottom-color: {t.ACCENT}; }}
    QFrame#palette-rows {{ background: transparent; }}
    QFrame#palette-row {{
        background: transparent;
        border-radius: 4px;
        border-left: 2px solid transparent;
    }}
    QFrame#palette-row:hover {{
        background: {t.SURFACE_HIGH};
    }}
    QFrame#palette-row[highlighted="true"] {{
        background: {t.SURFACE_PRESS};
        border-left: 2px solid {t.ACCENT};
    }}

    /* -- Tabs / misc ------------------------------------------------------ */
    QProgressBar {{
        background: {t.SURFACE_PANEL};
        border: 1px solid {t.BORDER};
        border-radius: 3px;
        text-align: center;
        color: {t.TEXT_SECONDARY};
        font-size: {t.SIZE_XS}px;
    }}
    QProgressBar::chunk {{
        background: {t.ACCENT};
    }}

    /* -- ToolTip ------------------------------------------------------- */
    QToolTip {{
        background: {t.SURFACE_HIGH};
        color: {t.TEXT_PRIMARY};
        border: 1px solid {t.BORDER_STRONG};
        border-radius: {t.RADIUS_BUTTON}px;
        padding: 5px 8px;
        font-family: {t.FONT_MONO};
        font-size: {t.SIZE_SM}px;
    }}
    """


# -- Generated indicator images ------------------------------------------------
# QSS ``image: url(...)`` wants a file path (data URIs are not supported by
# QStyleSheetStyle), so the checkbox switch knob and the combo chevron are
# rendered from tiny SVGs into PNGs in the user's temp dir the first time the
# sheet is built. Keeps the sheet token-driven with no PNGs to ship.

import hashlib
import tempfile
from pathlib import Path


def _asset_dir() -> Path:
    d = Path(tempfile.gettempdir()) / "phantomclick_qss"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _png_url(svg: str, w: int, h: int) -> str:
    """Render ``svg`` to a ``w`` x ``h`` PNG (cached by content hash) and
    return a QSS-safe forward-slash path."""
    from PySide6.QtCore import QByteArray, QRectF, Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    digest = hashlib.sha1(svg.encode("utf-8")).hexdigest()[:16]
    path = _asset_dir() / f"{digest}.png"
    if not path.exists():
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, QRectF(0, 0, w, h))
        painter.end()
        img.save(str(path), "PNG")
    return path.as_posix()


def _switch_uri(on):
    """28 x 12 switch interior: a 12 x 10 square knob at left (off) or
    right (on). ``None`` = disabled (knob in TEXT_DISABLED)."""
    if on is None:
        color, x = t.TEXT_DISABLED, 1
    elif on:
        color, x = t.ACCENT, 15
    else:
        color, x = t.STATUS_IDLE, 1
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="12" '
        f'viewBox="0 0 28 12"><rect x="{x}" y="1" width="12" height="10" '
        f'rx="1.5" fill="{color}"/></svg>'
    )
    return _png_url(svg, 28, 12)


def _chevron_uri() -> str:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" '
        'viewBox="0 0 24 24" fill="none" stroke="' + t.TEXT_SECONDARY + '" '
        'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M6 9l6 6 6-6"/></svg>'
    )
    return _png_url(svg, 12, 12)
