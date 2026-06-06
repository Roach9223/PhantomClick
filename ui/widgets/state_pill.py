"""``StatePill`` — small pill that shows a state next to a card title.

Lives in the title row of a card to give an at-a-glance status without
forcing the user to read field values. Two tones: ``"accent"`` (live coral
wash, default) and ``"neutral"`` (gray-on-panel, for "Not set" cases).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QWidget


class StatePill(QLabel):
    def __init__(
        self,
        text: str,
        tone: str = "accent",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "state-pill")
        if tone != "accent":
            self.setProperty("tone", tone)

    def set_state(self, text: str, tone: str = "accent") -> None:
        """Update text + tone in one call. Repolishes so QSS picks up
        the new tone attribute."""
        self.setText(text)
        new_tone = tone if tone != "accent" else None
        if self.property("tone") != new_tone:
            self.setProperty("tone", new_tone)
            self.style().unpolish(self)
            self.style().polish(self)
