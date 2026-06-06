"""Python-DSL bot authoring — the primary authoring surface.

A bot script is a plain ``.py`` file that constructs a :class:`Bot`,
decorates ordinary functions with ``@bot.rule(...)``, and either calls
``bot.run()`` in a ``if __name__ == "__main__":`` block (for standalone
execution) or lets the Studio run it.

Example::

    from rs3vision_studio.bot import Bot, find_color, click, wait

    bot = Bot(name="Draynor Willows", monitor=1)

    @bot.rule(phase="chopping")
    def chop_willow():
        m = find_color(target=0x4A2E1A, tol=22, min_pixels=30)
        if not m:
            return False
        click.at(m.point)
        wait(6000)
        return True

    @bot.rule(phase="scanning")
    def idle():
        wait(500)
        return True

    if __name__ == "__main__":
        bot.run()

Rules are evaluated in definition order each tick. The first rule
that returns a truthy value "wins" — subsequent rules are skipped
this tick. Return ``False`` / ``None`` to signal "I didn't fire,
try the next rule".

The primitives (:func:`find_color`, :func:`find_dtm`, :func:`click`,
:func:`wait`, etc.) use a per-tick :class:`RuntimeContext` set by
the :class:`BotRunner`. Running a bot outside the Studio (via
``python my_bot.py``) uses a standalone context path.
"""

from __future__ import annotations

from . import camera
from .api import (
    click,
    color_cluster,
    find_animation,
    find_any_color,
    find_color,
    find_dtm,
    find_interactable,
    find_ocr,
    find_player,
    is_animating,
    is_animating_recording,
    is_bank_open,
    player_is_animating,
    key,
    log,
    move,
    stop,
    template_match,
    tooltip_match,
    uptext,
    uptext_matches,
    wait,
    world,
    Match,
)
from .authoring import (
    AIBotStep,
    KIND_LABELS,
    deserialize_steps as deserialize_ai_steps,
    serialize_steps as serialize_ai_steps,
)
from .bot import Bot
from .compiler import compile_program, compile_user_bot, rule_name_for
from .loader import load_bot_from_path
from .runner import BotRunner
from .world import WorldState

__all__ = [
    "AIBotStep",
    "Bot",
    "BotRunner",
    "Match",
    "WorldState",
    "KIND_LABELS",
    "camera",
    "click",
    "color_cluster",
    "compile_program",
    "compile_user_bot",
    "deserialize_ai_steps",
    "find_animation",
    "find_any_color",
    "find_color",
    "find_dtm",
    "find_interactable",
    "find_ocr",
    "find_player",
    "is_animating",
    "is_animating_recording",
    "is_bank_open",
    "player_is_animating",
    "key",
    "load_bot_from_path",
    "log",
    "move",
    "rule_name_for",
    "serialize_ai_steps",
    "stop",
    "template_match",
    "tooltip_match",
    "uptext",
    "uptext_matches",
    "wait",
    "world",
]
