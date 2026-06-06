"""Procedures + Interrupts — the bot model that replaces the flat
priority-rule list.

Real bots aren't priority lists; they're sequences with reactive
overrides. "Fish until full" is a sequence (find spot → click → wait
for catch → loop). "If HP gets low" is a reactive override that can
fire any time and suspend whatever the bot was doing.

This module models exactly that:

- :class:`Procedure` — a named ordered list of steps. Steps run top to
  bottom, advancing the program counter after each one succeeds.
- :class:`Interrupt` — a trigger + a handler procedure name. Each
  tick, the runtime evaluates interrupts in declaration order; the
  first one whose trigger fires suspends the active procedure (saves
  pc on a small stack), runs the handler, and resumes when the
  handler completes.
- :class:`BotProgram` — the full bot definition: ``entry`` procedure
  name, dict of procedures keyed by name, list of interrupts.

Loop semantics: when the active procedure ends, control pops the
stack. If the stack is empty (i.e. the entry procedure just ended),
control restarts the entry procedure. So a one-procedure bot loops
forever, exactly like the old flat-list semantics.

Back-compat: a bundle that ships a flat list of steps (the legacy
shape) is upgraded by :func:`legacy_steps_to_program` into a single
``main`` procedure with no interrupts — same runtime behaviour, no
authoring change required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────


@dataclass
class Procedure:
    """One named sequence of steps."""

    name: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    # ``loop`` controls what happens when the last step ends.
    # - "stack" (default): pop the call stack — go back to whoever
    #   invoked us. If the stack is empty (we're the entry procedure)
    #   the runtime restarts us at pc=0.
    # - "abort": stop the bot when this procedure finishes.
    # Most bots leave this at "stack". "abort" is for diagnostic /
    # one-shot procedures.
    loop: str = "stack"

    def to_json(self) -> dict:
        return {
            "name": str(self.name),
            "steps": list(self.steps or []),
            "loop": self.loop or "stack",
        }

    @classmethod
    def from_json(cls, d: Any) -> "Procedure":
        if not isinstance(d, dict):
            return cls(name="unnamed")
        return cls(
            name=str(d.get("name") or "unnamed"),
            steps=list(d.get("steps") or []),
            loop=str(d.get("loop") or "stack"),
        )


# Interrupt trigger kinds — string discriminators in JSON.
TRIGGER_IF_INVENTORY_FULL = "if_inventory_full"
TRIGGER_IF_HP_BELOW = "if_hp_below"
TRIGGER_IF_ITEM_COUNT = "if_item_count"
TRIGGER_ON_CHAT = "on_chat"
TRIGGER_ON_PLAYER_MOVED = "on_player_moved_unexpectedly"
TRIGGER_ON_UPTEXT = "on_uptext"

VALID_TRIGGERS = (
    TRIGGER_IF_INVENTORY_FULL,
    TRIGGER_IF_HP_BELOW,
    TRIGGER_IF_ITEM_COUNT,
    TRIGGER_ON_CHAT,
    TRIGGER_ON_PLAYER_MOVED,
    TRIGGER_ON_UPTEXT,
)


# Special handler names. ``abort`` stops the bot; otherwise the
# handler must be the name of a procedure registered in the program.
HANDLER_ABORT = "abort"


@dataclass
class Interrupt:
    """A trigger + the procedure to run when it fires."""

    name: str
    trigger: str                            # one of VALID_TRIGGERS
    params: Dict[str, Any] = field(default_factory=dict)
    handler: str = ""                       # procedure name, or HANDLER_ABORT
    enabled: bool = True
    # Once an interrupt fires, suppress it for this many ticks before
    # it can fire again. Without this, a sticky condition (HP staying
    # low for several ticks) would re-trigger every tick.
    cooldown_ticks: int = 5

    def to_json(self) -> dict:
        return {
            "name": str(self.name),
            "trigger": str(self.trigger),
            "params": dict(self.params or {}),
            "handler": str(self.handler or ""),
            "enabled": bool(self.enabled),
            "cooldown_ticks": int(self.cooldown_ticks),
        }

    @classmethod
    def from_json(cls, d: Any) -> "Interrupt":
        if not isinstance(d, dict):
            return cls(name="unnamed", trigger=TRIGGER_IF_INVENTORY_FULL)
        trigger = d.get("trigger")
        if trigger not in VALID_TRIGGERS:
            trigger = TRIGGER_IF_INVENTORY_FULL
        return cls(
            name=str(d.get("name") or trigger),
            trigger=str(trigger),
            params=dict(d.get("params") or {}),
            handler=str(d.get("handler") or ""),
            enabled=bool(d.get("enabled", True)),
            cooldown_ticks=max(0, int(d.get("cooldown_ticks") or 0)),
        )


@dataclass
class BotProgram:
    """The full runnable bot definition."""

    entry: str = "main"
    procedures: Dict[str, Procedure] = field(default_factory=dict)
    interrupts: List[Interrupt] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "entry": str(self.entry),
            "procedures": {
                name: proc.to_json()
                for name, proc in self.procedures.items()
            },
            "interrupts": [i.to_json() for i in self.interrupts],
        }

    @classmethod
    def from_json(cls, d: Any) -> "BotProgram":
        if not isinstance(d, dict):
            return cls()
        entry = str(d.get("entry") or "main")
        raw_procs = d.get("procedures") or {}
        procedures: Dict[str, Procedure] = {}
        if isinstance(raw_procs, dict):
            # Storage shape A: ``{name: {steps: […]}}`` — preferred.
            for name, body in raw_procs.items():
                if isinstance(body, dict):
                    proc = Procedure.from_json({"name": name, **body})
                elif isinstance(body, list):
                    # Storage shape B: ``{name: [steps]}`` — accepted
                    # for back-compat with the legacy bundle layout.
                    proc = Procedure(name=str(name), steps=list(body))
                else:
                    continue
                procedures[name] = proc
        elif isinstance(raw_procs, list):
            # Storage shape C: ``[{name, steps, loop}]``. Less common.
            for item in raw_procs:
                if isinstance(item, dict):
                    proc = Procedure.from_json(item)
                    if proc.name:
                        procedures[proc.name] = proc
        interrupts = [
            Interrupt.from_json(item)
            for item in (d.get("interrupts") or [])
            if isinstance(item, dict)
        ]
        if entry not in procedures:
            # The entry can't point at a non-existent procedure —
            # fall back to the first procedure if any, else create
            # an empty ``main`` so the runtime fails fast at start.
            if procedures:
                entry = next(iter(procedures))
            else:
                procedures["main"] = Procedure(name="main")
                entry = "main"
        return cls(
            entry=entry,
            procedures=procedures,
            interrupts=interrupts,
        )

    # ── Convenience accessors ─────────────────────────────────────
    def procedure(self, name: str) -> Optional[Procedure]:
        return self.procedures.get(name)

    def step_count(self) -> int:
        return sum(len(p.steps) for p in self.procedures.values())


# ─────────────────────────────────────────────────────────────────
# Back-compat: flat list ↔ program
# ─────────────────────────────────────────────────────────────────


def legacy_steps_to_program(steps: List[Dict[str, Any]], *, entry: str = "main") -> BotProgram:
    """Wrap a flat list of steps into a single-procedure program.

    Used to bridge the old custom-bot path: ``cfg["ai_user_bot_steps"]``
    is still a flat list, and a freshly-created bundle starts with
    ``procedures.main = []`` (also a flat list shape). Both flow
    through this helper so the runner sees a uniform program.
    """
    return BotProgram(
        entry=entry,
        procedures={entry: Procedure(name=entry, steps=list(steps or []))},
        interrupts=[],
    )


def program_from_bundle_dict(d: Any) -> BotProgram:
    """Build a :class:`BotProgram` from a bundle's ``procedures.json``.

    Accepts both the new shape (``{entry, procedures, interrupts}``)
    and the back-compat shape (a bare list of step dicts, treated as
    the entry procedure named ``main``).
    """
    if isinstance(d, list):
        return legacy_steps_to_program(d)
    return BotProgram.from_json(d if isinstance(d, dict) else {})
