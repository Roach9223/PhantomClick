"""Helper for tooltips that surface a keyboard shortcut alongside the body.

Format::

    Begin clicking. Waits for the Pre-start delay so you can alt-tab into
    the target window before the first click.

    Shortcut: F6

The blank line + "Shortcut:" suffix is enough visual separation in
:class:`QToolTip` (which auto-wraps body text). We deliberately don't read
the command registry here — the registry is the source of truth for what's
*bound*, but the displayed text is the card's responsibility. Decoupling
lets us evolve labels independently from binding state.
"""

from __future__ import annotations

from typing import Optional


def tooltip(description: str, shortcut: Optional[str] = None) -> str:
    if not shortcut:
        return description
    return f"{description}\n\nShortcut: {shortcut}"
