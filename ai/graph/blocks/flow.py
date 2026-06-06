"""Flow-control blocks: OnStart, Stop, Wait, IfElse."""

from __future__ import annotations

import time
from typing import Any, Dict

from .base import Block, Param, Port


class OnStartBlock(Block):
    identifier = "flow.on_start"
    name = "On Start"
    category = "Flow"
    description = "Entry point. Fires once per tick."
    color = (40, 90, 40)

    inputs = []
    outputs = [Port("trigger", kind="trigger")]
    params = [
        Param(
            "phase",
            default="",
            kind="text",
            description=(
                "Optional phase label — appears on the Dashboard phase chip "
                "while this tick is running. Leave blank to keep the current phase."
            ),
        ),
    ]

    def execute(self, ctx, phase: str = "", **_: Any) -> Dict[str, Any]:
        out: Dict[str, Any] = {"trigger": True}
        if phase:
            out["phase"] = phase
        return out


class StopBlock(Block):
    identifier = "flow.stop"
    name = "Stop"
    category = "Flow"
    description = "Halts the script."
    color = (120, 40, 40)

    inputs = [Port("trigger", kind="trigger")]
    outputs = []
    params = []

    def execute(self, ctx, **_: Any) -> Dict[str, Any]:
        ctx.request_stop("flow.stop block reached")
        return {}


class WaitBlock(Block):
    identifier = "flow.wait"
    name = "Wait"
    category = "Flow"
    description = "Pause for a given number of milliseconds."
    color = (70, 70, 70)

    inputs = [Port("trigger", kind="trigger")]
    outputs = [Port("done", kind="trigger")]
    params = [
        Param("ms", default=500, kind="int", description="Milliseconds to sleep."),
        Param(
            "phase",
            default="",
            kind="text",
            description=(
                "Optional phase label — e.g. 'waiting' or 'recovering'. Shows "
                "on the Dashboard chip while this block runs."
            ),
        ),
    ]

    def execute(self, ctx, ms: int = 500, phase: str = "", **_: Any) -> Dict[str, Any]:
        # Sleep in small slices so a user Stop press halts promptly.
        target = time.monotonic() + ms / 1000.0
        while time.monotonic() < target:
            if ctx.should_stop():
                return {}
            time.sleep(min(0.05, target - time.monotonic()))
        out: Dict[str, Any] = {"done": True}
        if phase:
            out["phase"] = phase
        return out


class IfElseBlock(Block):
    identifier = "flow.if_else"
    name = "If / Else"
    category = "Flow"
    description = "Branch based on a boolean input."
    color = (70, 60, 100)

    inputs = [Port("condition", kind="data")]
    outputs = [Port("true", kind="trigger"), Port("false", kind="trigger")]
    params = []

    def execute(self, ctx, condition: Any = None, **_: Any) -> Dict[str, Any]:
        if condition:
            return {"true": True}
        return {"false": True}


class CompareBlock(Block):
    identifier = "flow.compare"
    name = "Compare"
    category = "Flow"
    description = (
        "Numeric / string comparison. Emits a boolean on 'result' and fires "
        "either 'true' or 'false' trigger. Useful feeding flow.if_else."
    )
    color = (70, 60, 100)

    inputs = [
        Port("a", kind="data"),
        Port("b", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("result", kind="data"),   # bool
        Port("true", kind="trigger"),
        Port("false", kind="trigger"),
    ]
    params = [
        Param(
            "op",
            default="==",
            kind="choice",
            choices=["==", "!=", "<", "<=", ">", ">="],
        ),
    ]

    def execute(
        self, ctx, a: Any = None, b: Any = None, op: str = "==", **_: Any
    ) -> Dict[str, Any]:
        try:
            if op == "==":
                r = a == b
            elif op == "!=":
                r = a != b
            elif op == "<":
                r = a < b
            elif op == "<=":
                r = a <= b
            elif op == ">":
                r = a > b
            elif op == ">=":
                r = a >= b
            else:
                r = False
        except TypeError:
            r = False
        return {"result": r, ("true" if r else "false"): True}


class LogBlock(Block):
    identifier = "flow.log"
    name = "Log Message"
    category = "Flow"
    description = "Write a message to the log panel. Passes the trigger through."
    color = (60, 70, 60)

    inputs = [
        Port("value", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [Port("done", kind="trigger")]
    params = [
        Param(
            "message",
            default="",
            kind="text",
            description="Printed before 'value'. Leave blank to log just the value.",
        ),
    ]

    def execute(
        self, ctx, value: Any = None, message: str = "", **_: Any
    ) -> Dict[str, Any]:
        prefix = message.strip() if message else ""
        if prefix and value is not None:
            ctx.log(f"{prefix}: {value!r}")
        elif prefix:
            ctx.log(prefix)
        else:
            ctx.log(repr(value))
        return {"done": True}


class PickLargestBlock(Block):
    identifier = "flow.pick_largest"
    name = "Pick Largest Cluster"
    category = "Flow"
    description = "From a list of clusters, pick the one with the most points."
    color = (60, 70, 60)

    inputs = [
        Port("clusters", kind="data"),
        Port("trigger", kind="trigger"),
    ]
    outputs = [
        Port("cluster", kind="data"),    # list[(x, y)] or None
        Port("size", kind="data"),       # int
        Port("done", kind="trigger"),
    ]
    params = []

    def execute(self, ctx, clusters=None, **_: Any) -> Dict[str, Any]:
        cl = list(clusters or [])
        if not cl:
            return {"cluster": None, "size": 0, "done": True}
        biggest = max(cl, key=len)
        return {"cluster": biggest, "size": len(biggest), "done": True}
