"""``FeatureToggle`` — checkbox row for binary humanization features.

Wraps a QCheckBox with a tooltip and registers itself into the App's
shared ``_adv_vars`` dict so the Realism preset can flip it.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QWidget

from .. import theme as t
from ui.config_io import save_config


class FeatureToggle(QCheckBox):
    def __init__(
        self,
        app,
        text: str,
        cfg_key: str,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(text, parent)
        self.app = app
        self._key = cfg_key
        self.setChecked(bool(app.cfg.get(cfg_key, False)))
        if tooltip:
            self.setToolTip(tooltip)
        self.toggled.connect(self._on_toggled)
        app._adv_vars[cfg_key] = self

    def _on_toggled(self, checked: bool) -> None:
        self.app.cfg[self._key] = bool(checked)
        save_config(self.app.cfg)
        self.app._push_config_to_clicker()
