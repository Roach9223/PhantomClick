"""RecorderStep: a single step in an auto-recorded click sequence.

The Clicker engine in `modules.clicker` cycles through a list of these in
recorder mode. Each step carries its own zone, click type/mode, and the
randomized delay range that elapses BEFORE the next step fires.

Step ``kind`` is a string discriminator so new step types can be added
without growing a forest of mutually-exclusive booleans:

  - ``KIND_CLICK``  fixed-zone click (zone + click_type/mode/count)
  - ``KIND_PAUSE``  pure wait, no click
  - ``KIND_TRACK``  click on a moving template (per-step captured PNG)
  - ``KIND_LOOP``   jump back to an earlier step (forever or N times)
  - ``KIND_COLOR``  click any pixel matching a sampled colour
  - ``KIND_KEY``    press a key combo (turns Record into a full macro)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from .zone_selector import Zone


KIND_CLICK = "click"
KIND_PAUSE = "pause"
KIND_TRACK = "track"
KIND_LOOP = "loop"
KIND_COLOR = "color"
KIND_KEY = "key"
_VALID_KINDS = (KIND_CLICK, KIND_PAUSE, KIND_TRACK, KIND_LOOP, KIND_COLOR,
                KIND_KEY)

# Coordinate space tags for ``RecorderStep.capture_rect``. See the field
# comment on the dataclass for why both exist.
CAPTURE_SPACE_DIP = "dip"
CAPTURE_SPACE_PHYSICAL = "physical"
# Same two tags for ``RecorderStep.color_search_rect``. Kept as separate
# names so a grep for either field's space finds only its own call sites.
COLOR_SEARCH_SPACE_DIP = CAPTURE_SPACE_DIP
COLOR_SEARCH_SPACE_PHYSICAL = CAPTURE_SPACE_PHYSICAL


def _new_step_id() -> str:
    """Stable per-step ID used to key the on-disk template PNG file."""
    return uuid.uuid4().hex[:12]


def new_view_id() -> str:
    """Suffix for an alternate-view PNG: ``<step_id>_view_<view_id>.png``."""
    return uuid.uuid4().hex[:8]


def template_paths_of(step: "RecorderStep") -> list[str]:
    """Every template path (primary + extra views) a step references.
    Empty for non-track steps and for track steps with nothing captured."""
    if step.kind != KIND_TRACK:
        return []
    out: list[str] = []
    if step.template_path:
        out.append(str(step.template_path))
    for p in step.extra_template_paths or []:
        if p:
            out.append(str(p))
    return out


def orphaned_template_paths(step: "RecorderStep",
                            remaining: list["RecorderStep"]) -> list[str]:
    """Template paths of ``step`` that no step in ``remaining`` still uses.

    Duplicated steps from older builds share one PNG, so removing a step
    must only take a file with it when it is the last reference. Paths
    are compared as normalized strings; both sides come from the same
    ``os.path.relpath`` writer so that is sufficient.
    """
    def _norm(p: str) -> str:
        return str(p).replace("\\", "/").lower()

    still_used = {
        _norm(p)
        for other in remaining
        if other is not step
        for p in template_paths_of(other)
    }
    return [p for p in template_paths_of(step) if _norm(p) not in still_used]


def _parse_rgb(raw: object) -> Optional[tuple[int, int, int]]:
    """Coerce a JSON-loaded ``[r, g, b]`` list into a clamped int tuple."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    try:
        return (
            max(0, min(255, int(raw[0]))),
            max(0, min(255, int(raw[1]))),
            max(0, min(255, int(raw[2]))),
        )
    except (TypeError, ValueError):
        return None


@dataclass
class RecorderStep:
    zone: Optional[Zone] = None
    click_type: str = "left"        # "left" | "right" | "middle"
    click_mode: str = "single"      # "single" | "double"
    shape: str = "rect"             # default shape if user hasn't drawn yet
    click_count: int = 1            # how many clicks fire here before advancing
    delay_min: float = 1.0          # gap between clicks; doubles as pause / inter-visit duration for non-click kinds
    delay_max: float = 3.0
    kind: str = KIND_CLICK
    # User-controlled enable flag. When False, the engine rotates past
    # this step without firing, equivalent to "comment it out for now."
    # Persists across sessions so disabled steps survive a restart. Used
    # for testing iteration ("does the macro work without the key step?")
    # without forcing the user to delete + recreate.
    enabled: bool = True
    # Optional human-readable name shown in the row header and loop-target
    # dropdown. "" = no label, header falls back to the step number + kind.
    # Capped at 80 chars on load to avoid layout blow-up from a pasted essay.
    label: str = ""

    # KIND_TRACK fields (ignored otherwise). template_path is relative to the
    # config dir so launching from a different cwd still finds the PNG.
    # extra_template_paths holds additional "views" of the same target,
    # useful when an NPC rotates / changes camera angle. The engine matches
    # against ALL of them every frame and uses whichever scores highest.
    #
    # capture_rect is ``(x1, y1, x2, y2)`` of the region the primary template
    # was grabbed from. New captures store it in PHYSICAL pixels (the mss
    # ``monitors[0]`` space, matching what the tracker searches and what
    # the template PNG actually contains) and set ``capture_rect_space`` to
    # "physical". Configs written before that change hold Qt DIP coords and
    # load with ``capture_rect_space == "dip"``; consumers must convert
    # (``utils.dpi_cursor.dip_rect_to_physical``) before handing the rect
    # to mss or the tracker. On a 100% DPI single-monitor setup the two
    # spaces coincide, which is why the bug went unnoticed for so long.
    step_id: str = field(default_factory=_new_step_id)
    template_path: Optional[str] = None
    template_size: tuple[int, int] = (0, 0)        # (w, h) of the primary template
    capture_rect: Optional[tuple[int, int, int, int]] = None
    capture_rect_space: str = CAPTURE_SPACE_PHYSICAL
    extra_template_paths: list[str] = field(default_factory=list)
    extra_template_sizes: list[tuple[int, int]] = field(default_factory=list)
    tracker_threshold: float = 0.65
    tracker_search_radius: int = 250
    tracker_scale_jitter: float = 0.15             # ± fraction; 0 = single-scale
    tracker_full_rescan: bool = True
    tracker_update_rate_hz: float = 20.0
    # Per-step timeout for poll-based step kinds (KIND_TRACK + KIND_COLOR).
    # 0.0 = wait forever (current behavior, default for legacy configs);
    # > 0 = if the target hasn't been found for this many seconds, the
    # engine dispatches ``on_timeout``. ``on_timeout`` is one of:
    #   "skip" → advance to the next step
    #   "stop" → halt the engine
    timeout_seconds: float = 0.0
    on_timeout: str = "skip"

    # KIND_LOOP fields. loop_target_step_id is a step.step_id reference (NOT
    # an index) so reordering doesn't break the link; resolved at run time.
    # loop_count = 0 means "loop forever"; > 0 = jump back this many more
    # times before continuing past the loop step.
    loop_target_step_id: Optional[str] = None
    loop_count: int = 0

    # KIND_COLOR fields. The engine clicks any pixel within `color_tolerance`
    # (RGB euclidean distance) of `color_target_rgb` OR any colour in
    # ``color_extra_rgbs``, useful for buttons with multi-tone gradients,
    # anti-aliased edges, or game UI that varies slightly between states.
    # Tolerance is shared across all colors. 0 = exact match; ~30 is a
    # sensible default; ~80 is permissive. ``color_search_rect`` is
    # ``(x1, y1, x2, y2)`` in PHYSICAL pixels (mss ``monitors[0]`` space)
    # bounding the per-cycle scan to the monitor the primary color was
    # picked on; ``None`` falls back to the full virtual screen. ``zone``
    # (DIP, like every other zone) optionally narrows where matches count.
    color_target_rgb: Optional[tuple[int, int, int]] = None
    color_tolerance: int = 30
    color_search_rect: Optional[tuple[int, int, int, int]] = None
    color_extra_rgbs: list[tuple[int, int, int]] = field(default_factory=list)

    # KIND_KEY fields. ``key_combo`` is a +-joined modifier-then-key string
    # parsed by ``modules.key_timer.parse_combo`` (e.g. "z", "f1",
    # "ctrl+shift+f5"). ``key_hold_s`` keeps the key down for that many
    # seconds before releasing, useful for charge-then-release game inputs;
    # 0 = ordinary tap. ``key_repeat`` fires the same combo N times back to
    # back within the step (default 1) to handle "press space three times to
    # eat" macros without needing three separate steps.
    key_combo: str = ""
    key_hold_s: float = 0.0
    key_repeat: int = 1
    # Coordinate space of ``color_search_rect``. New steps are written in
    # physical mss pixels (the eyedropper stores the picked monitor's
    # physical bounds). Configs saved before this tag existed carry Qt
    # DIPs, so from_json defaults an untagged rect to "dip" and the
    # engine converts at grab time.
    color_search_rect_space: str = COLOR_SEARCH_SPACE_PHYSICAL

    def to_json(self) -> dict:
        out: dict = {
            "zone": self.zone.to_json() if self.zone is not None else None,
            "click_type": self.click_type,
            "click_mode": self.click_mode,
            "shape": self.shape,
            "click_count": int(self.click_count),
            "delay_min": float(self.delay_min),
            "delay_max": float(self.delay_max),
            "kind": self.kind,
            "step_id": self.step_id,
            "enabled": bool(self.enabled),
            "label": str(self.label or ""),
        }
        if self.kind == KIND_TRACK:
            out.update({
                "template_path": self.template_path,
                "template_size": list(self.template_size),
                "capture_rect": (list(self.capture_rect)
                                  if self.capture_rect is not None else None),
                "capture_rect_space": str(self.capture_rect_space or CAPTURE_SPACE_PHYSICAL),
                "extra_template_paths": list(self.extra_template_paths),
                "extra_template_sizes": [list(sz)
                                          for sz in self.extra_template_sizes],
                "tracker_threshold": float(self.tracker_threshold),
                "tracker_search_radius": int(self.tracker_search_radius),
                "tracker_scale_jitter": float(self.tracker_scale_jitter),
                "tracker_full_rescan": bool(self.tracker_full_rescan),
                "tracker_update_rate_hz": float(self.tracker_update_rate_hz),
                "timeout_seconds": float(self.timeout_seconds),
                "on_timeout": str(self.on_timeout or "skip"),
            })
        elif self.kind == KIND_LOOP:
            out.update({
                "loop_target_step_id": self.loop_target_step_id,
                "loop_count": int(self.loop_count),
            })
        elif self.kind == KIND_COLOR:
            out.update({
                "color_target_rgb": (list(self.color_target_rgb)
                                       if self.color_target_rgb is not None
                                       else None),
                "color_tolerance": int(self.color_tolerance),
                "color_search_rect": (list(self.color_search_rect)
                                        if self.color_search_rect is not None
                                        else None),
                "color_search_rect_space": str(
                    self.color_search_rect_space or COLOR_SEARCH_SPACE_PHYSICAL),
                "color_extra_rgbs": [list(rgb) for rgb in self.color_extra_rgbs],
                "timeout_seconds": float(self.timeout_seconds),
                "on_timeout": str(self.on_timeout or "skip"),
            })
        elif self.kind == KIND_KEY:
            out.update({
                "key_combo": str(self.key_combo or ""),
                "key_hold_s": float(self.key_hold_s),
                "key_repeat": int(self.key_repeat),
            })
        return out

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["RecorderStep"]:
        if not isinstance(d, dict):
            return None
        zone = Zone.from_json(d.get("zone"))
        # Migrate legacy is_pause bool. Unknown kinds fall back to click so a
        # forward-rolled config doesn't crash an older build.
        kind = d.get("kind")
        if kind not in _VALID_KINDS:
            kind = KIND_PAUSE if d.get("is_pause") else KIND_CLICK
        cap = d.get("capture_rect")
        cap_tuple = (tuple(int(v) for v in cap)
                      if isinstance(cap, (list, tuple)) and len(cap) == 4
                      else None)
        # Configs written before the physical-pixel change carry no space
        # tag; those rects were Qt DIPs, so default the tag accordingly.
        cap_space = d.get("capture_rect_space")
        if cap_space not in (CAPTURE_SPACE_DIP, CAPTURE_SPACE_PHYSICAL):
            cap_space = CAPTURE_SPACE_DIP if cap_tuple is not None else CAPTURE_SPACE_PHYSICAL
        csr = d.get("color_search_rect")
        csr_tuple = (tuple(int(v) for v in csr)
                      if isinstance(csr, (list, tuple)) and len(csr) == 4
                      else None)
        # Same "missing tag = dip" rule as capture_rect_space, and for the
        # same reason: the untagged rects were written from Qt geometry.
        csr_space = d.get("color_search_rect_space")
        if csr_space not in (COLOR_SEARCH_SPACE_DIP, COLOR_SEARCH_SPACE_PHYSICAL):
            csr_space = (COLOR_SEARCH_SPACE_DIP if csr_tuple is not None
                         else COLOR_SEARCH_SPACE_PHYSICAL)
        ts = d.get("template_size")
        ts_tuple = (int(ts[0]), int(ts[1])) if (
            isinstance(ts, (list, tuple)) and len(ts) == 2) else (0, 0)
        # Extra views (multi-template). Older configs won't have these keys
        #, they default to empty lists, behavior is identical to before.
        ext_paths = d.get("extra_template_paths") or []
        ext_paths = [str(p) for p in ext_paths if isinstance(p, str) and p]
        ext_sizes_raw = d.get("extra_template_sizes") or []
        ext_sizes: list[tuple[int, int]] = []
        for sz in ext_sizes_raw:
            if isinstance(sz, (list, tuple)) and len(sz) == 2:
                ext_sizes.append((int(sz[0]), int(sz[1])))
            else:
                ext_sizes.append((0, 0))
        # Pad sizes to match paths so indexing is always safe.
        while len(ext_sizes) < len(ext_paths):
            ext_sizes.append((0, 0))
        ext_sizes = ext_sizes[:len(ext_paths)]
        return cls(
            zone=zone,
            click_type=d.get("click_type", "left"),
            click_mode=d.get("click_mode", "single"),
            shape=d.get("shape", zone.shape if zone is not None else "rect"),
            click_count=max(1, int(d.get("click_count", 1))),
            delay_min=float(d.get("delay_min", 1.0)),
            delay_max=float(d.get("delay_max", 3.0)),
            kind=kind,
            step_id=str(d.get("step_id") or _new_step_id()),
            template_path=d.get("template_path"),
            template_size=ts_tuple,
            capture_rect=cap_tuple,
            capture_rect_space=cap_space,
            extra_template_paths=ext_paths,
            extra_template_sizes=ext_sizes,
            tracker_threshold=float(d.get("tracker_threshold", 0.65)),
            tracker_search_radius=int(d.get("tracker_search_radius", 250)),
            tracker_scale_jitter=float(d.get("tracker_scale_jitter", 0.15)),
            tracker_full_rescan=bool(d.get("tracker_full_rescan", True)),
            tracker_update_rate_hz=float(d.get("tracker_update_rate_hz", 20.0)),
            loop_target_step_id=(d.get("loop_target_step_id") or None),
            loop_count=max(0, int(d.get("loop_count", 0) or 0)),
            color_target_rgb=_parse_rgb(d.get("color_target_rgb")),
            color_tolerance=max(0, min(255, int(d.get("color_tolerance", 30) or 30))),
            color_search_rect=csr_tuple,
            color_search_rect_space=csr_space,
            color_extra_rgbs=[
                rgb for rgb in (
                    _parse_rgb(item) for item in (d.get("color_extra_rgbs") or [])
                ) if rgb is not None
            ],
            key_combo=str(d.get("key_combo") or ""),
            key_hold_s=max(0.0, float(d.get("key_hold_s", 0.0) or 0.0)),
            key_repeat=max(1, int(d.get("key_repeat", 1) or 1)),
            # Default True so configs predating this field are unaffected.
            enabled=bool(d.get("enabled", True)),
            # Cap at 80 to keep the row header from blowing up if a user
            # pastes an essay. "" means no label (header reverts to step + kind).
            label=str(d.get("label") or "")[:80],
            timeout_seconds=max(0.0, float(d.get("timeout_seconds", 0.0) or 0.0)),
            # Clamp to known values so a forward-rolled config can't surprise
            # the engine with an unknown action.
            on_timeout=(d.get("on_timeout")
                        if d.get("on_timeout") in ("skip", "stop")
                        else "skip"),
        )


def serialize_steps(steps: list[RecorderStep]) -> list[dict]:
    return [s.to_json() for s in steps]


def deserialize_steps(raw: object) -> list[RecorderStep]:
    if not isinstance(raw, list):
        return []
    out: list[RecorderStep] = []
    for item in raw:
        s = RecorderStep.from_json(item)
        if s is not None:
            out.append(s)
    return out
