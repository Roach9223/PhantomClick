"""Python-DSL bot authoring, the primary authoring surface.

A bot script is a plain ``.py`` file that constructs a :class:`Bot`
and decorates ordinary functions with ``@bot.rule(...)``. The
PhantomClick AI tab imports the script and runs it via
:class:`BotRunner`.

Example::

    from ai.bot import Bot, find_color, click, wait

    bot = Bot(name="Draynor Willows", monitor=1)

    @bot.rule(phase="chopping")
    def chop_willow():
        m = find_color(target=0x4A2E1A, tol=22, min_pixels=30)
        if not m:
            return False
        click.at(m.point)
        wait(6000)
        return True

    @bot.rule(phase="scanning", idle=True)
    def idle():
        wait(500)
        return True

Rules are evaluated in definition order each tick. The first rule
that returns a truthy value "wins"; later rules are skipped this
tick. Return ``False`` / ``None`` to signal "I didn't fire, try the
next rule". Mark the fallthrough rule ``idle=True`` (or return
:data:`IDLE`) so the AFK watchdog still counts the tick as dry.

All coordinates a bot sees (ROIs in, ``Match.point`` out, ``click.at``
targets) are physical screen pixels. The runner's frame source and
mapper translate to and from frame pixels internally.
"""

from __future__ import annotations

# Load the ``world`` submodule BEFORE importing the ``world()`` function
# from api. Importing a submodule binds it as an attribute of this
# package, so if it loaded later it would silently replace the function
# and ``from ai.bot import world`` would hand bots a module.
from .world import WorldState
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
from .bot import IDLE, Bot
from .compiler import compile_program, compile_user_bot, rule_name_for
from .loader import load_bot_from_path
from .runner import BotRunner

assert callable(world), "ai.bot.world must be the api function, not the submodule"

__all__ = [
    "AIBotStep",
    "Bot",
    "BotRunner",
    "IDLE",
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
