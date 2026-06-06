"""Block base class + registry + NodeGraphQt adapter.

Every executable unit in a Studio script is a :class:`Block` subclass.
Blocks declare inputs / outputs / parameters as class attributes and
implement :meth:`Block.execute`. Subclassing auto-registers the block
into :data:`REGISTRY` so both the node-editor sidebar and the runtime
can find it by identifier.

Each block is also surfaced as a **NodeGraphQt node** via
:func:`make_ngq_node_cls`. The editor builds these node classes once at
startup and registers them with the graph.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type


# ─────────────────────────────────────────────────────────────────
# Port / parameter descriptors
# ─────────────────────────────────────────────────────────────────


@dataclass
class Port:
    """A named input or output port on a block."""

    name: str
    kind: str = "data"  # "trigger" | "data" — trigger ports carry control flow


@dataclass
class Param:
    """A user-settable parameter, surfaced in the properties panel."""

    name: str
    default: Any = None
    kind: str = "text"  # "text" | "int" | "float" | "bool" | "color_hex" | "choice"
    choices: List[str] = field(default_factory=list)
    # Optional callable that returns a fresh list of choices at node-add time
    # (used for dropdowns whose options come from disk — e.g. template files).
    # Takes precedence over the static `choices` field when provided.
    choices_provider: Optional[Callable[[], List[str]]] = None
    description: str = ""


# ─────────────────────────────────────────────────────────────────
# Block base + registry
# ─────────────────────────────────────────────────────────────────


class Block(ABC):
    """Executable unit. Subclass, declare ports/params, implement execute."""

    # Class-level metadata — override in subclasses.
    identifier: str = ""          # e.g. "color.find"
    name: str = ""                # human display, e.g. "Find Color"
    category: str = ""            # e.g. "Color"
    description: str = ""         # shown in tooltips
    example: str = ""             # optional — inline help/docs example
    color: tuple = (60, 60, 90)   # node header color (R, G, B)

    inputs: List[Port] = []
    outputs: List[Port] = []
    params: List[Param] = []

    @abstractmethod
    def execute(
        self, ctx: "RuntimeContext", **kwargs: Any  # noqa: F821
    ) -> Dict[str, Any]:
        """Run the block. Returns a dict mapping **output port name → value**.

        For trigger-out ports, a truthy value means "fire downstream".
        For data-out ports, the value is whatever downstream consumers
        take as input by the same port name.

        `ctx` provides logging + frame capture + shared state helpers.
        """

    def __init_subclass__(cls, **kwargs: Any) -> None:  # auto-register
        super().__init_subclass__(**kwargs)
        if cls.identifier:
            if cls.identifier in REGISTRY:
                raise ValueError(
                    f"duplicate block identifier: {cls.identifier!r} "
                    f"({REGISTRY[cls.identifier].__name__} vs {cls.__name__})"
                )
            REGISTRY[cls.identifier] = cls


REGISTRY: Dict[str, Type[Block]] = {}


def iter_by_category() -> Dict[str, List[Type[Block]]]:
    """Group registered blocks by their `category` string, for the sidebar."""
    out: Dict[str, List[Type[Block]]] = {}
    for cls in REGISTRY.values():
        out.setdefault(cls.category or "Misc", []).append(cls)
    for lst in out.values():
        lst.sort(key=lambda c: c.name)
    return dict(sorted(out.items()))


# ─────────────────────────────────────────────────────────────────
# NodeGraphQt adapter — a factory that builds BaseNode subclasses
# from Block subclasses. Lets the editor render + connect blocks
# using the declarative metadata above.
# ─────────────────────────────────────────────────────────────────


def make_ngq_node_cls(block_cls: Type[Block]):
    """Produce a NodeGraphQt `BaseNode` subclass for `block_cls`.

    The resulting class has:

    * One input port per :attr:`Block.inputs`.
    * One output port per :attr:`Block.outputs`.
    * One property per :attr:`Block.params` (edited in the properties panel).
    * A `_block_cls` attribute pointing at the originating Block subclass
      — the runtime uses this to instantiate + execute the block.
    """
    from NodeGraphQt import BaseNode

    class _StudioNode(BaseNode):
        __identifier__ = "rs3vision"
        NODE_NAME = block_cls.name or block_cls.__name__

        _block_cls = block_cls

        def __init__(self) -> None:
            super().__init__()
            for port in block_cls.inputs:
                color = _port_color(port.kind)
                self.add_input(port.name, color=color) if color else self.add_input(port.name)
            for port in block_cls.outputs:
                color = _port_color(port.kind)
                self.add_output(port.name, color=color) if color else self.add_output(port.name)
            for param in block_cls.params:
                _add_property_for_param(self, param)
            # Color the node header by category.
            r, g, b = block_cls.color
            self.set_color(r, g, b)
            # Tooltip is applied by StudioGraph.create_node AFTER the graph
            # finishes constructing the node — NodeGraphQt's internal
            # `_tooltip_disable` runs post-__init__ and would otherwise
            # clobber anything we set here.

    _StudioNode.__name__ = f"{block_cls.__name__}Node"
    _StudioNode.__qualname__ = _StudioNode.__name__
    return _StudioNode


# ─────────────────────────────────────────────────────────────────
# Port visual style
# ─────────────────────────────────────────────────────────────────


# Yellow = "trigger" (control-flow). Blue = "data" (values). Keeps the
# wiring intent visually obvious — users can tell at a glance which
# ports fire execution vs carry payloads.
_PORT_COLORS = {
    "trigger": (245, 200, 60),
    "data": (80, 160, 220),
}


def _port_color(kind: str):
    return _PORT_COLORS.get(kind)


def _add_property_for_param(node, param: Param) -> None:
    """Add a NodeGraphQt property appropriate to the param's `kind`."""
    # Dynamic dropdown (e.g. template files in a folder).
    if param.kind == "choice" and param.choices_provider is not None:
        try:
            items = list(param.choices_provider()) or [""]
        except Exception:
            items = [""]
        # Always include a blank slot so the field can be cleared.
        if "" not in items:
            items = [""] + items
        node.add_combo_menu(param.name, param.name, items=items)
        if param.default is not None and str(param.default) in items:
            node.set_property(param.name, str(param.default))
        return
    if param.kind == "choice" and param.choices:
        node.add_combo_menu(
            param.name, param.name, items=list(param.choices)
        )
        if param.default is not None and str(param.default) in param.choices:
            node.set_property(param.name, str(param.default))
        return
    if param.kind == "bool":
        node.add_checkbox(param.name, "", text=param.name, state=bool(param.default))
        return
    default = "" if param.default is None else str(param.default)
    node.add_text_input(param.name, param.name, text=default)


# ─────────────────────────────────────────────────────────────────
# Helpers for reading parameters back out of a node instance.
# The runtime needs to fetch current param values at execution time.
# ─────────────────────────────────────────────────────────────────


def read_param(node, param: Param) -> Any:
    """Pull the current value of `param` off a NodeGraphQt node.

    Coerces string inputs to the right Python type based on `param.kind`.
    """
    raw = node.get_property(param.name)
    if raw is None or raw == "":
        return param.default
    if param.kind == "int":
        try:
            return int(str(raw), 0)  # "0xFFFF00" works too
        except (TypeError, ValueError):
            return param.default
    if param.kind == "float":
        try:
            return float(raw)
        except (TypeError, ValueError):
            return param.default
    if param.kind == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if param.kind == "color_hex":
        return _parse_color_hex(raw)
    return raw  # text, choice


def _parse_color_hex(raw: Any) -> Optional[int]:
    if isinstance(raw, int):
        return raw
    s = str(raw).strip().lower()
    if not s:
        return None
    if s.startswith("#"):
        s = s[1:]
    if s.startswith("0x"):
        s = s[2:]
    try:
        return int(s, 16)
    except ValueError:
        return None
