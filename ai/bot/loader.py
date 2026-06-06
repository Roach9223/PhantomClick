"""Import a ``.py`` bot script and return its top-level ``bot`` object.

Bot scripts are regular Python modules. Each is expected to expose a
module-level ``bot`` variable bound to a :class:`Bot` instance. We
load them by file path (not by dotted name) so tasks can reference
scripts outside the package tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from .bot import Bot


def load_bot_from_path(path: Path) -> Bot:
    """Import ``path`` as a module and return its ``bot`` attribute."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"bot script not found: {path}")

    module_name = f"_rs3v_bot_{path.stem}_{abs(hash(str(path))) & 0xFFFF:04x}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load bot script {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Keep the user's stack trace visible.
        raise ImportError(
            f"bot script {path} raised during import: {type(e).__name__}: {e}"
        ) from e

    bot = getattr(module, "bot", None)
    if bot is None:
        raise ValueError(
            f"bot script {path} does not expose a module-level ``bot`` object. "
            "Add ``bot = Bot(name=...)`` near the top of the file."
        )
    if not isinstance(bot, Bot):
        raise ValueError(
            f"bot script {path} ``bot`` is not a rs3vision_studio.bot.Bot instance "
            f"(got {type(bot).__name__})"
        )
    if not bot.rules:
        # Not fatal, but warn — a bot with no rules is a no-op.
        print(f"[loader] warning: bot {bot.name!r} has no @bot.rule definitions")
    return bot
