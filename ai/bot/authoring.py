"""AIBotStep — user-authored bot step, the AI-mode analogue of
:class:`modules.recorder.RecorderStep`.

Mirrors RecorderStep's "single dataclass with a kind discriminator"
shape, validation style, and JSON round-trip. The kinds are tuned for
bot use cases (find-then-click, find-then-key, conditional branches
on inventory / HP) rather than Record mode's macro use cases
(track-and-click, hold-key-N-seconds).

A user assembles a list of these in the AI tab's authoring section.
At Start time, :func:`ai.bot.compiler.compile_user_bot` walks the list
and synthesizes a :class:`ai.bot.bot.Bot` with one ``@bot.rule`` per
step. The runner then executes that bot identically to a library bot.

**Loop / branch semantics.** Compiled rules fire under the runner's
"first-match-wins each tick" model, NOT a program-counter sequencer.
``loop_back`` means "this rule wins the next N ticks." Conditional
branches (``if_inventory_full`` etc.) gate the rule on a runtime
predicate; a ``branch_target_step_id`` points at another step's
closure that fires inline when the predicate is true.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ─────────────────────────────────────────────────────────────────
# Kind discriminators
# ─────────────────────────────────────────────────────────────────

KIND_FIND_COLOR_CLICK = "find_color_click"
KIND_FIND_COLOR_KEY = "find_color_keypress"
KIND_FIND_DTM_CLICK = "find_dtm_click"
KIND_FIND_ANIMATION_CLICK = "find_animation_click"
KIND_FIND_CAPTURE_CLICK = "find_capture_click"
KIND_ZONE_CLICK = "zone_click"
KIND_WAIT = "wait"
KIND_KEY_PRESS = "key_press"
KIND_IF_INVENTORY_FULL = "if_inventory_full"
KIND_IF_HP_BELOW = "if_hp_below_pct"
KIND_IF_ITEM_COUNT = "if_item_count"
KIND_LOOP_BACK = "loop_back"
KIND_UPTEXT_CHECK = "uptext_check"

VALID_KINDS = (
    KIND_FIND_COLOR_CLICK,
    KIND_FIND_COLOR_KEY,
    KIND_FIND_DTM_CLICK,
    KIND_FIND_ANIMATION_CLICK,
    KIND_FIND_CAPTURE_CLICK,
    KIND_ZONE_CLICK,
    KIND_WAIT,
    KIND_KEY_PRESS,
    KIND_IF_INVENTORY_FULL,
    KIND_IF_HP_BELOW,
    KIND_IF_ITEM_COUNT,
    KIND_LOOP_BACK,
    KIND_UPTEXT_CHECK,
)
# Back-compat alias for tools that imported the underscored name during
# the initial build of this module.
_VALID_KINDS = VALID_KINDS


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def new_step_id() -> str:
    """Stable per-step ID, used to key conditional / loop targets and
    UI row state (expansion, focus) so reordering doesn't break links.
    """
    return uuid.uuid4().hex[:12]


# Back-compat alias.
_new_step_id = new_step_id


def _parse_rgb(raw) -> Optional[Tuple[int, int, int]]:
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


def _parse_rect(raw) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        return tuple(int(v) for v in raw)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────
# AIBotStep
# ─────────────────────────────────────────────────────────────────


@dataclass
class AIBotStep:
    # ── Common ──────────────────────────────────────────────────
    step_id: str = field(default_factory=_new_step_id)
    kind: str = KIND_FIND_COLOR_CLICK
    enabled: bool = True
    label: str = ""                  # capped at 80 on load
    phase: str = ""                  # optional; tints rule chip + dashboard
    # Random wait fired AFTER a successful action — applies to every
    # "I just did something" kind (click, key). 0 = no extra wait.
    after_min_ms: int = 600
    after_max_ms: int = 1200

    # ── Detection / target (find_color_*, find_dtm_click) ──────
    color_target_rgb: Optional[Tuple[int, int, int]] = None
    color_extra_rgbs: list[Tuple[int, int, int]] = field(default_factory=list)
    color_tolerance: int = 20                # 0..100
    color_cts_mode: int = 2                  # 1 | 2 | 3 (HSL default)
    color_min_pixels: int = 5
    color_cluster_dist: int = 4
    roi: Optional[Tuple[int, int, int, int]] = None  # (x, y, w, h) abs px
    dtm_template_path: Optional[str] = None

    # ── Wait ───────────────────────────────────────────────────
    wait_min_ms: int = 500
    wait_max_ms: int = 1500

    # ── Key press (key_press, find_color_keypress) ─────────────
    key_combo: str = ""              # parse_combo()-compatible
    key_hold_s: float = 0.0
    key_repeat: int = 1

    # ── Conditional / branch ───────────────────────────────────
    inventory_threshold: int = 27    # if_inventory_full: ≥N filled
    hp_threshold_pct: int = 50       # if_hp_below_pct: <N%
    item_name: str = ""              # if_item_count / find_color_click filter
    item_count_op: str = ">="        # one of >=, <=, ==, >, <
    item_count_threshold: int = 1
    branch_target_step_id: Optional[str] = None  # step.step_id of action

    # ── Animation detector (find_animation_click) ──────────────
    anim_window_frames: int = 5       # ring-buffer size
    anim_min_flickers: int = 2        # minimum pair-diffs per tile

    # ── Capture-template match (find_capture_click) ────────────
    # Names a snapshot in the active bundle's assets/snapshots/.
    # Compiler resolves to a path via bundle.asset_path(name, "snapshot").
    capture_name: str = ""
    # Match-confidence floor for cv2.matchTemplate(TM_CCOEFF_NORMED).
    # 0.7 is permissive enough to absorb camera-zoom + lighting drift,
    # tight enough that scenery doesn't false-match.
    capture_match_threshold: float = 0.7

    # ── Zone click ─────────────────────────────────────────────
    # Serialized Zone (rect / circle / polygon) — same shape
    # RecorderStep uses, accepted by Zone.from_json.
    zone_json: Optional[dict] = None

    # ── Loop back ──────────────────────────────────────────────
    loop_target_step_id: Optional[str] = None
    loop_count: int = 0              # 0 = forever

    # ── Uptext check ───────────────────────────────────────────
    uptext_pattern: str = ""
    uptext_is_regex: bool = False

    # ── Closed-loop verification ────────────────────────────────
    # ``verify`` is a dict {signal, params, timeout_ms} describing
    # what to watch for after the action fires. None = no check, the
    # step is considered complete the moment it returns truthy.
    # See ai/algorithms/verify.py for the signal vocabulary.
    verify: Optional[dict] = None
    # ``on_fail`` is one of "retry", "abort", or "goto_procedure:<name>".
    # Retry has an implicit small budget (3 attempts) before escalating
    # to the next on_fail in the chain. Abort halts the bot.
    # goto_procedure:<name> suspends the current procedure and runs the
    # named recovery procedure inline.
    on_fail: str = "retry"
    # Per-step retry budget — used when on_fail == "retry". Counter
    # lives in the runner state, not here. Stored on the step so the
    # editor can expose it.
    retry_budget: int = 3

    # ──────────────────────────────────────────────────────────
    def to_json(self) -> dict:
        out: dict = {
            "step_id": self.step_id,
            "kind": self.kind,
            "enabled": bool(self.enabled),
            "label": str(self.label or "")[:80],
            "phase": str(self.phase or "")[:32],
            "after_min_ms": int(self.after_min_ms),
            "after_max_ms": int(self.after_max_ms),
        }
        if self.verify is not None:
            out["verify"] = dict(self.verify)
        if self.on_fail and self.on_fail != "retry":
            out["on_fail"] = str(self.on_fail)
        if self.retry_budget != 3:
            out["retry_budget"] = int(self.retry_budget)
        if self.kind in (KIND_FIND_COLOR_CLICK, KIND_FIND_COLOR_KEY):
            out.update({
                "color_target_rgb": (
                    list(self.color_target_rgb)
                    if self.color_target_rgb else None
                ),
                "color_extra_rgbs": [list(rgb) for rgb in self.color_extra_rgbs],
                "color_tolerance": int(self.color_tolerance),
                "color_cts_mode": int(self.color_cts_mode),
                "color_min_pixels": int(self.color_min_pixels),
                "color_cluster_dist": int(self.color_cluster_dist),
                "roi": list(self.roi) if self.roi else None,
            })
            if self.kind == KIND_FIND_COLOR_KEY:
                out.update({
                    "key_combo": str(self.key_combo or ""),
                    "key_hold_s": float(self.key_hold_s),
                    "key_repeat": int(self.key_repeat),
                })
        elif self.kind == KIND_FIND_DTM_CLICK:
            out.update({
                "dtm_template_path": (
                    str(self.dtm_template_path) if self.dtm_template_path else None
                ),
                "roi": list(self.roi) if self.roi else None,
            })
        elif self.kind == KIND_WAIT:
            out.update({
                "wait_min_ms": int(self.wait_min_ms),
                "wait_max_ms": int(self.wait_max_ms),
            })
        elif self.kind == KIND_KEY_PRESS:
            out.update({
                "key_combo": str(self.key_combo or ""),
                "key_hold_s": float(self.key_hold_s),
                "key_repeat": int(self.key_repeat),
            })
        elif self.kind == KIND_IF_INVENTORY_FULL:
            out.update({
                "inventory_threshold": int(self.inventory_threshold),
                "branch_target_step_id": self.branch_target_step_id,
            })
        elif self.kind == KIND_IF_HP_BELOW:
            out.update({
                "hp_threshold_pct": int(self.hp_threshold_pct),
                "branch_target_step_id": self.branch_target_step_id,
            })
        elif self.kind == KIND_IF_ITEM_COUNT:
            out.update({
                "item_name": str(self.item_name or ""),
                "item_count_op": str(self.item_count_op or ">="),
                "item_count_threshold": int(self.item_count_threshold),
                "branch_target_step_id": self.branch_target_step_id,
            })
        elif self.kind == KIND_FIND_ANIMATION_CLICK:
            out.update({
                "roi": list(self.roi) if self.roi else None,
                "anim_window_frames": int(self.anim_window_frames),
                "anim_min_flickers": int(self.anim_min_flickers),
            })
        elif self.kind == KIND_FIND_CAPTURE_CLICK:
            out.update({
                "capture_name": str(self.capture_name or ""),
                "capture_match_threshold": float(self.capture_match_threshold),
                "roi": list(self.roi) if self.roi else None,
            })
        elif self.kind == KIND_ZONE_CLICK:
            out.update({
                "zone_json": (dict(self.zone_json) if self.zone_json else None),
            })
        elif self.kind == KIND_LOOP_BACK:
            out.update({
                "loop_target_step_id": self.loop_target_step_id,
                "loop_count": int(self.loop_count),
            })
        elif self.kind == KIND_UPTEXT_CHECK:
            out.update({
                "uptext_pattern": str(self.uptext_pattern or ""),
                "uptext_is_regex": bool(self.uptext_is_regex),
            })
        return out

    @classmethod
    def from_json(cls, d) -> Optional["AIBotStep"]:
        if not isinstance(d, dict):
            return None
        kind = d.get("kind")
        if kind not in _VALID_KINDS:
            kind = KIND_WAIT          # safest no-op fallback
        return cls(
            step_id=str(d.get("step_id") or _new_step_id()),
            kind=kind,
            enabled=bool(d.get("enabled", True)),
            label=str(d.get("label") or "")[:80],
            phase=str(d.get("phase") or "")[:32],
            after_min_ms=max(0, int(d.get("after_min_ms", 600) or 0)),
            after_max_ms=max(0, int(d.get("after_max_ms", 1200) or 0)),
            color_target_rgb=_parse_rgb(d.get("color_target_rgb")),
            color_extra_rgbs=[
                rgb for rgb in (
                    _parse_rgb(item)
                    for item in (d.get("color_extra_rgbs") or [])
                ) if rgb is not None
            ],
            color_tolerance=max(0, min(100, int(d.get("color_tolerance", 20) or 20))),
            color_cts_mode=int(d.get("color_cts_mode", 2) or 2),
            color_min_pixels=max(1, int(d.get("color_min_pixels", 5) or 5)),
            color_cluster_dist=max(1, int(d.get("color_cluster_dist", 4) or 4)),
            roi=_parse_rect(d.get("roi")),
            dtm_template_path=(
                str(d.get("dtm_template_path"))
                if d.get("dtm_template_path") else None
            ),
            wait_min_ms=max(0, int(d.get("wait_min_ms", 500) or 0)),
            wait_max_ms=max(0, int(d.get("wait_max_ms", 1500) or 0)),
            key_combo=str(d.get("key_combo") or ""),
            key_hold_s=max(0.0, float(d.get("key_hold_s", 0.0) or 0.0)),
            key_repeat=max(1, int(d.get("key_repeat", 1) or 1)),
            inventory_threshold=max(0, min(28, int(d.get("inventory_threshold", 27) or 27))),
            hp_threshold_pct=max(0, min(100, int(d.get("hp_threshold_pct", 50) or 50))),
            item_name=str(d.get("item_name") or ""),
            item_count_op=(d.get("item_count_op") or ">=") if d.get("item_count_op") in (">=", "<=", "==", ">", "<") else ">=",
            item_count_threshold=max(0, int(d.get("item_count_threshold", 1) or 1)),
            anim_window_frames=max(2, int(d.get("anim_window_frames", 5) or 5)),
            anim_min_flickers=max(1, int(d.get("anim_min_flickers", 2) or 2)),
            capture_name=str(d.get("capture_name") or ""),
            capture_match_threshold=max(
                0.1, min(1.0, float(d.get("capture_match_threshold", 0.7) or 0.7))
            ),
            zone_json=(
                dict(d["zone_json"]) if isinstance(d.get("zone_json"), dict) else None
            ),
            branch_target_step_id=(d.get("branch_target_step_id") or None),
            loop_target_step_id=(d.get("loop_target_step_id") or None),
            loop_count=max(0, int(d.get("loop_count", 0) or 0)),
            uptext_pattern=str(d.get("uptext_pattern") or ""),
            uptext_is_regex=bool(d.get("uptext_is_regex", False)),
            verify=(dict(d["verify"]) if isinstance(d.get("verify"), dict) else None),
            on_fail=str(d.get("on_fail") or "retry"),
            retry_budget=max(1, int(d.get("retry_budget", 3) or 3)),
        )


def serialize_steps(steps: list[AIBotStep]) -> list[dict]:
    return [s.to_json() for s in steps]


def deserialize_steps(raw) -> list[AIBotStep]:
    if not isinstance(raw, list):
        return []
    out: list[AIBotStep] = []
    for item in raw:
        s = AIBotStep.from_json(item)
        if s is not None:
            out.append(s)
    return out


# Pretty kind labels for the editor's "+ Add step" menu and the
# fallback rule names used when ``step.label`` is empty.
KIND_LABELS: dict[str, str] = {
    KIND_FIND_COLOR_CLICK: "Find color → click",
    KIND_FIND_COLOR_KEY: "Find color → press key",
    KIND_FIND_DTM_CLICK: "Find DTM template → click",
    KIND_FIND_ANIMATION_CLICK: "Find animation → click",
    KIND_FIND_CAPTURE_CLICK: "Find captured snapshot → click",
    KIND_ZONE_CLICK: "Click in zone",
    KIND_WAIT: "Wait",
    KIND_KEY_PRESS: "Press key",
    KIND_IF_INVENTORY_FULL: "If inventory full",
    KIND_IF_HP_BELOW: "If HP below %",
    KIND_IF_ITEM_COUNT: "If item count …",
    KIND_LOOP_BACK: "Loop back",
    KIND_UPTEXT_CHECK: "Check uptext",
}
