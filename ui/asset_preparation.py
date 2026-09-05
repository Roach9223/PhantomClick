"""Cancellable background preparation of optional wiki assets."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class AssetPreparation(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)  # list of errors

    def __init__(self, names, cache_root: Path, parent=None, client_factory=None):
        super().__init__(parent)
        self.names = tuple(dict.fromkeys(names))
        self.cache_root = cache_root
        self.cancelled = threading.Event()
        self.client_factory = client_factory

    def cancel(self):
        self.cancelled.set()

    def start(self):
        threading.Thread(target=self._run, name="prepare-bot-assets", daemon=True).start()

    def _run(self):
        errors = []
        try:
            from ai.wiki import default_client
            from ai.wiki.client import _slugify
            client = (self.client_factory or default_client)(self.cache_root)
            for i, name in enumerate(self.names):
                if self.cancelled.is_set():
                    break
                self.progress.emit(i, len(self.names), name)
                if (self.cache_root / "items" / f"{_slugify(name)}.png").is_file():
                    continue
                try:
                    if client.fetch_item_image(name) is None:
                        errors.append(f"No icon found for {name}")
                except Exception as e:
                    errors.append(f"{name}: {e}")
        except Exception as e:
            errors.append(str(e))
        # Closing a window can destroy its QObject while a bounded HTTP
        # request finishes. The worker owns no widgets and never starts a bot.
        try:
            self.completed.emit(errors)
        except RuntimeError:
            pass
