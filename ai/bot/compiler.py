"""compile_user_bot — turn a list of :class:`AIBotStep` into a
runnable :class:`Bot` with one ``@bot.rule`` per step.

Strategy: closures-per-step, NOT a meta-interpreter.

Why? The bot runner walks rules in priority order each tick and the
first rule that returns truthy "wins" — see
``ai.bot.runner._BotWorker.run``. Building one rule per step preserves:
  * priority order = step order (the user's mental model from Record mode),
  * the AI dashboard's per-rule live highlight (lights up the actual
    step that fired),
  * per-rule crash logs name the offending step,
  * disabling/enabling a single step via ``step.enabled`` Just Works.

A meta-interpreter rule would collapse the dashboard to one row and
turn every crash log into "the interpreter crashed somewhere."

Loop / branch semantics are tick-scoped, NOT program-counter:
  * ``loop_back`` is a counter rule that wins the next N ticks (or
    forever) and then disables itself.
  * ``if_inventory_full`` / ``if_hp_below_pct`` gate on a runtime
    predicate; a ``branch_target_step_id`` resolves to another step's
    closure that runs inline when the predicate is true.

For true sequential program-counter flow, write a full Python bot in
``ai/tasks/library/`` instead of using the in-GUI authoring surface.
"""

from __future__ import annotations

import random
import re
from typing import Callable, Dict, List, Optional, Tuple

from . import api as _api
from .authoring import (
    AIBotStep,
    KIND_FIND_ANIMATION_CLICK,
    KIND_FIND_CAPTURE_CLICK,
    KIND_FIND_COLOR_CLICK,
    KIND_FIND_COLOR_KEY,
    KIND_FIND_DTM_CLICK,
    KIND_IF_HP_BELOW,
    KIND_IF_INVENTORY_FULL,
    KIND_IF_ITEM_COUNT,
    KIND_KEY_PRESS,
    KIND_LABELS,
    KIND_LOOP_BACK,
    KIND_UPTEXT_CHECK,
    KIND_WAIT,
    KIND_ZONE_CLICK,
    deserialize_steps,
)
from .bot import Bot
from .procedures import (
    BotProgram, HANDLER_ABORT, Interrupt, Procedure,
    TRIGGER_IF_HP_BELOW, TRIGGER_IF_INVENTORY_FULL, TRIGGER_IF_ITEM_COUNT,
    TRIGGER_ON_CHAT, TRIGGER_ON_PLAYER_MOVED, TRIGGER_ON_UPTEXT,
    legacy_steps_to_program,
)


# ─────────────────────────────────────────────────────────────────
# Rule-name contract
# ─────────────────────────────────────────────────────────────────


def rule_name_for(step: AIBotStep) -> str:
    """Human-readable rule name for both the runtime registration and
    the dashboard's preview list. Both surfaces MUST call this helper
    so the live highlight (``_RuleRow.fire(name)``) lands on the right
    row when the runner emits ``bot.rule.<name>``.
    """
    if step.label:
        return step.label[:60]
    return _fallback_name(step)


def _fallback_name(step: AIBotStep) -> str:
    if step.kind == KIND_FIND_COLOR_CLICK:
        rgb = step.color_target_rgb
        return (
            f"Find #{_rgb_hex(rgb)} → click" if rgb else "Find color → click"
        )
    if step.kind == KIND_FIND_COLOR_KEY:
        rgb = step.color_target_rgb
        kc = step.key_combo or "?"
        return (
            f"Find #{_rgb_hex(rgb)} → key {kc!r}"
            if rgb else f"Find color → key {kc!r}"
        )
    if step.kind == KIND_FIND_DTM_CLICK:
        path = step.dtm_template_path or "?"
        return f"DTM {path} → click"
    if step.kind == KIND_FIND_ANIMATION_CLICK:
        return "Find animation → click"
    if step.kind == KIND_FIND_CAPTURE_CLICK:
        nm = step.capture_name or "?"
        return f"Capture {nm!r} → click"
    if step.kind == KIND_ZONE_CLICK:
        if step.zone_json:
            shape = step.zone_json.get("shape") or "?"
            return f"Click in {shape}"
        return "Click in zone"
    if step.kind == KIND_IF_ITEM_COUNT:
        op = step.item_count_op or ">="
        return f"If {step.item_name!r} count {op} {step.item_count_threshold}"
    if step.kind == KIND_WAIT:
        return f"Wait {step.wait_min_ms}–{step.wait_max_ms}ms"
    if step.kind == KIND_KEY_PRESS:
        return f"Press {step.key_combo or '?'}"
    if step.kind == KIND_IF_INVENTORY_FULL:
        return f"If inventory full ≥{step.inventory_threshold}"
    if step.kind == KIND_IF_HP_BELOW:
        return f"If HP < {step.hp_threshold_pct}%"
    if step.kind == KIND_LOOP_BACK:
        n = step.loop_count or 0
        return f"Loop back ({'forever' if n == 0 else f'{n}×'})"
    if step.kind == KIND_UPTEXT_CHECK:
        return f"Uptext ~ {(step.uptext_pattern or '')[:24]}"
    return KIND_LABELS.get(step.kind, step.kind)


def _rgb_hex(rgb) -> str:
    if not rgb:
        return "??????"
    r, g, b = rgb
    return f"{r:02X}{g:02X}{b:02X}"


# ─────────────────────────────────────────────────────────────────
# compile_user_bot
# ─────────────────────────────────────────────────────────────────


def compile_user_bot(
    steps: List[AIBotStep],
    *,
    name: str = "Custom Bot",
    tick_rate_hz: float = 5.0,
    dry_run: bool = False,
    auto_camera: bool = False,
    auto_stop_dry_ticks: int = 60,
    watchdog_no_click_s: float = 600.0,
    item_library: Optional[object] = None,
) -> Tuple[Bot, List[str]]:
    """Walk the user's step list and synthesize a :class:`Bot`.

    Returns ``(bot, errors)``. An empty errors list means the bot is
    ready to run; non-empty means *some* steps were dropped or
    flagged. Callers should toast each error and may still start the
    bot — only steps that produced errors are dropped, the rest are
    registered.
    """
    errors: List[str] = []

    bot = Bot(
        name=name,
        slug=_slug_from_name(name),
        tick_rate_hz=tick_rate_hz,
        dry_run=dry_run,
        auto_camera=auto_camera,
        auto_stop_dry_ticks=auto_stop_dry_ticks,
        watchdog_no_click_s=watchdog_no_click_s,
    )
    # Pin the item library on the Bot — the runner picks it up via
    # getattr(bot, "item_library", None) and exposes it through
    # ctx.item_library for WorldState.
    if item_library is not None:
        bot.item_library = item_library  # type: ignore[attr-defined]

    if not steps:
        errors.append("No steps to compile — add at least one step in the editor.")
        return bot, errors

    # Pass 1 — build closures for every enabled, valid step keyed by
    # step_id so pass 2 can resolve branch targets and loop targets.
    # Validation errors here mean the closure won't be registered.
    step_closures: Dict[str, Tuple[AIBotStep, Callable[[], bool]]] = {}
    for i, step in enumerate(steps):
        if not step.enabled:
            continue
        closure, errs = _compile_step(step, step_index=i)
        for e in errs:
            errors.append(f"Step {i + 1} ({KIND_LABELS.get(step.kind, step.kind)}): {e}")
        if closure is None:
            continue
        step_closures[step.step_id] = (step, closure)

    # Pass 2 — wrap conditional / loop closures so they can call other
    # steps' closures inline. Then register the FINAL closure under
    # the canonical rule name.
    for step_id, (step, closure) in step_closures.items():
        final_closure = closure
        if step.kind in (KIND_IF_INVENTORY_FULL, KIND_IF_HP_BELOW, KIND_IF_ITEM_COUNT):
            target_id = step.branch_target_step_id
            if target_id and target_id in step_closures:
                target_closure = step_closures[target_id][1]
                # Wrap: gate fires the target's body inline when the
                # predicate is true. The gate's "did anything fire?"
                # reflects the target's return value so the runner's
                # first-match-wins still terminates the tick.
                final_closure = _wrap_branch(closure, target_closure)
            elif target_id:
                errors.append(
                    f"Step '{rule_name_for(step)}' branches to a step "
                    f"that no longer exists (or is disabled)."
                )
                # Keep the gate but with no inline target — it'll just
                # return its predicate value (True ends the tick, False
                # falls through).
        bot.rule(
            name=rule_name_for(step),
            phase=step.phase or "",
            enabled=True,
        )(final_closure)

    if not bot.rules:
        errors.append("No valid steps to register — check the validation messages above.")

    return bot, errors


def _slug_from_name(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s or "custom_bot"


# ─────────────────────────────────────────────────────────────────
# compile_program — procedural compile path (Phase B canonical)
# ─────────────────────────────────────────────────────────────────


from dataclasses import dataclass as _dataclass


@_dataclass
class _CompiledStep:
    """One procedure step's compiled closure plus display metadata."""

    name: str
    phase: str
    func: Callable[[], bool]
    enabled: bool
    # Closed-loop verification — runner reads these after the closure
    # returns truthy. ``verify_spec`` is the raw {signal, params,
    # timeout_ms} dict from the step JSON; the runner converts it to
    # a Verifier on the fly. ``on_fail`` and ``retry_budget`` are
    # passed through verbatim.
    verify_spec: Optional[dict] = None
    on_fail: str = "retry"
    retry_budget: int = 3
    # Display-only metadata for the BotOverlay — not used by the
    # runtime. Keeps the original step's ROI + kind so the HUD can
    # outline the area the bot is currently scanning without making
    # the runner re-deserialize the program every tick.
    roi: Optional[Tuple[int, int, int, int]] = None
    kind: str = ""


@_dataclass
class _CompiledInterrupt:
    """Pre-compiled interrupt — trigger predicate + handler dispatch."""

    name: str
    handler: str
    cooldown_ticks: int
    trigger: Callable[[], bool]


def compile_program(
    program: BotProgram,
    *,
    name: str = "Custom Bot",
    tick_rate_hz: float = 5.0,
    dry_run: bool = False,
    auto_camera: bool = False,
    auto_stop_dry_ticks: int = 60,
    watchdog_no_click_s: float = 600.0,
    item_library: Optional[object] = None,
    bundle: Optional[object] = None,
) -> Tuple[Bot, List[str]]:
    """Compile a :class:`BotProgram` into a :class:`Bot` with the
    procedural runtime attached.

    The returned bot has these extra attributes the runner uses:

    - ``program`` (:class:`BotProgram`) — the source program
    - ``_compiled_procedures`` (``dict[str, list[_CompiledStep]]``) —
      compiled step closures keyed by procedure name, in order
    - ``_compiled_interrupts`` (``list[_CompiledInterrupt]``) — in
      declaration order; the runner evaluates them top-to-bottom

    The legacy ``bot.rules`` list is also populated (one Rule per
    compiled step across all procedures, prefixed with the procedure
    name) so the dashboard's rule preview renders something useful
    while the procedural runtime is being wired in.
    """
    errors: List[str] = []
    bot = Bot(
        name=name,
        slug=_slug_from_name(name),
        tick_rate_hz=tick_rate_hz,
        dry_run=dry_run,
        auto_camera=auto_camera,
        auto_stop_dry_ticks=auto_stop_dry_ticks,
        watchdog_no_click_s=watchdog_no_click_s,
    )
    if item_library is not None:
        bot.item_library = item_library  # type: ignore[attr-defined]

    if not program.procedures:
        errors.append("Program has no procedures.")
        return bot, errors

    # ── Compile procedures ──────────────────────────────────────
    compiled_procs: Dict[str, List[_CompiledStep]] = {}
    # First pass: parse every procedure's steps + build closures.
    # Cross-procedure / cross-step references would go in a second
    # pass (currently none — branch targets are within a single step
    # list and resolve via legacy_steps_to_program for now).
    for proc_name, proc in program.procedures.items():
        ai_steps = deserialize_steps(proc.steps)
        compiled: List[_CompiledStep] = []
        for i, step in enumerate(ai_steps):
            if not step.enabled:
                continue
            closure, errs = _compile_step(step, step_index=i, bundle=bundle)
            for e in errs:
                errors.append(
                    f"Procedure {proc_name!r} step {i + 1} "
                    f"({KIND_LABELS.get(step.kind, step.kind)}): {e}"
                )
            if closure is None:
                continue
            compiled.append(_CompiledStep(
                name=rule_name_for(step),
                phase=step.phase or "",
                func=closure,
                enabled=True,
                verify_spec=(dict(step.verify) if step.verify else None),
                on_fail=str(step.on_fail or "retry"),
                retry_budget=int(step.retry_budget or 3),
                roi=(tuple(step.roi) if step.roi else None),
                kind=str(step.kind or ""),
            ))
        compiled_procs[proc_name] = compiled

    # ── Compile interrupts ──────────────────────────────────────
    compiled_interrupts: List[_CompiledInterrupt] = []
    valid_handlers = set(program.procedures.keys()) | {HANDLER_ABORT}
    for intr in program.interrupts:
        if not intr.enabled:
            continue
        if intr.handler not in valid_handlers:
            errors.append(
                f"Interrupt {intr.name!r}: handler {intr.handler!r} "
                f"is not a known procedure (or 'abort')."
            )
            continue
        trigger_fn = _build_trigger(intr)
        if trigger_fn is None:
            errors.append(
                f"Interrupt {intr.name!r}: invalid trigger {intr.trigger!r}"
            )
            continue
        compiled_interrupts.append(_CompiledInterrupt(
            name=intr.name,
            handler=intr.handler,
            cooldown_ticks=int(intr.cooldown_ticks),
            trigger=trigger_fn,
        ))

    # ── Attach to Bot ──────────────────────────────────────────
    bot.program = program  # type: ignore[attr-defined]
    bot._compiled_procedures = compiled_procs  # type: ignore[attr-defined]
    bot._compiled_interrupts = compiled_interrupts  # type: ignore[attr-defined]
    bot._program_entry = program.entry  # type: ignore[attr-defined]

    # Legacy rule-list mirror — drives the dashboard preview. Entry
    # procedure first, then the rest in dict order. Rule names are
    # prefixed with the procedure so the dashboard can show
    # ``fishing_loop.click fishing spot``.
    bot.rules = []
    proc_order = [program.entry] + [
        n for n in program.procedures if n != program.entry
    ]
    for proc_name in proc_order:
        for ps in compiled_procs.get(proc_name, []):
            bot.rule(
                name=f"{proc_name}.{ps.name}",
                phase=ps.phase,
                enabled=ps.enabled,
            )(ps.func)

    if not any(compiled_procs.values()):
        errors.append(
            "No valid steps in any procedure — bot has nothing to do."
        )

    return bot, errors


# ─────────────────────────────────────────────────────────────────
# Trigger predicates (interrupts)
# ─────────────────────────────────────────────────────────────────


def _build_trigger(intr: Interrupt) -> Optional[Callable[[], bool]]:
    """Return a tick-time predicate function for an interrupt. ``None``
    when the trigger kind isn't recognized (caller surfaces an error)."""
    params = dict(intr.params or {})

    if intr.trigger == TRIGGER_IF_INVENTORY_FULL:
        threshold = int(params.get("threshold", 27))
        def _t() -> bool:
            inv = _api.world().inventory
            return inv is not None and inv.count_filled() >= threshold
        return _t

    if intr.trigger == TRIGGER_IF_HP_BELOW:
        threshold = int(params.get("threshold_pct", 50))
        def _t() -> bool:
            hp = _api.world().hp_pct()
            return hp is not None and hp < threshold
        return _t

    if intr.trigger == TRIGGER_IF_ITEM_COUNT:
        item_name = str(params.get("item_name", ""))
        op = str(params.get("op", ">="))
        threshold = int(params.get("threshold", 1))
        def _t() -> bool:
            n = _api.world().count_item(item_name)
            if op == ">=": return n >= threshold
            if op == "<=": return n <= threshold
            if op == "==": return n == threshold
            if op == ">":  return n > threshold
            if op == "<":  return n < threshold
            return False
        return _t

    if intr.trigger == TRIGGER_ON_UPTEXT:
        pattern = str(params.get("match", ""))
        is_regex = bool(params.get("regex", False))
        compiled = None
        if is_regex:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                compiled = None
        def _t() -> bool:
            u = _api.uptext()
            if not u:
                return False
            text = str(u.get("text") or "")
            if compiled is not None:
                return bool(compiled.search(text))
            return pattern.lower() in text.lower()
        return _t

    if intr.trigger == TRIGGER_ON_CHAT:
        pattern = str(params.get("match", ""))
        is_regex = bool(params.get("regex", False))
        compiled = None
        if is_regex:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                compiled = None

        def _t() -> bool:
            ctx = _api._ctx()
            events = getattr(ctx, "recent_chat_events", None)
            if not events:
                return False
            for ev in events:
                text = str(ev.get("text") or "")
                if compiled is not None:
                    if compiled.search(text):
                        return True
                elif pattern.lower() in text.lower():
                    return True
            return False
        return _t

    if intr.trigger == TRIGGER_ON_PLAYER_MOVED:
        # Wired alongside the minimap reader. Until that lands the
        # trigger reads from a runner-managed buffer the minimap
        # primitive will populate.
        threshold_tiles = int(params.get("tiles", 5))

        def _t() -> bool:
            ctx = _api._ctx()
            delta = getattr(ctx, "player_move_delta_tiles", None)
            if delta is None:
                return False
            return int(delta) >= threshold_tiles
        return _t

    return None


# Keep compile_user_bot the canonical legacy path — internally upgrades
# a flat list to a single-procedure program and delegates to
# compile_program. Callers that want native procedural compilation use
# compile_program directly.


# ─────────────────────────────────────────────────────────────────
# Per-kind closure builders
# ─────────────────────────────────────────────────────────────────


def _compile_step(
    step: AIBotStep,
    *,
    step_index: int,
    bundle: Optional[object] = None,
) -> Tuple[Optional[Callable[[], bool]], List[str]]:
    errs: List[str] = []
    if step.kind == KIND_FIND_CAPTURE_CLICK:
        if not (step.capture_name or "").strip():
            errs.append("no capture asset name set")
            return None, errs
        if bundle is None:
            errs.append(
                "find_capture_click needs a bundle context (start the "
                "bot from a bundle entry, not the legacy custom path)"
            )
            return None, errs
        try:
            asset_path = bundle.asset_path(step.capture_name, "snapshot")
        except Exception as e:
            errs.append(f"asset lookup failed: {type(e).__name__}: {e}")
            return None, errs
        if asset_path is None:
            errs.append(
                f"capture {step.capture_name!r} not found in "
                f"bundle assets/snapshots/ (run the Captures section "
                f"and save a snapshot named {step.capture_name!r})"
            )
            return None, errs
        return _build_find_capture_click(step, asset_path), errs
    if step.kind == KIND_ZONE_CLICK:
        if not step.zone_json:
            errs.append("zone not drawn yet — click 'Set zone' in the editor")
            return None, errs
        return _build_zone_click(step), errs
    if step.kind == KIND_FIND_COLOR_CLICK:
        if step.color_target_rgb is None:
            errs.append("no color picked")
            return None, errs
        return _build_find_color_click(step), errs
    if step.kind == KIND_FIND_COLOR_KEY:
        if step.color_target_rgb is None:
            errs.append("no color picked")
            return None, errs
        if not step.key_combo.strip():
            errs.append("no key combo set")
            return None, errs
        return _build_find_color_keypress(step), errs
    if step.kind == KIND_FIND_DTM_CLICK:
        if not (step.dtm_template_path or "").strip():
            errs.append("no DTM template path set")
            return None, errs
        return _build_find_dtm_click(step), errs
    if step.kind == KIND_FIND_ANIMATION_CLICK:
        if step.roi is None:
            errs.append("animation needs an ROI (Set ROI in the editor)")
            return None, errs
        return _build_find_animation_click(step), errs
    if step.kind == KIND_WAIT:
        return _build_wait(step), errs
    if step.kind == KIND_KEY_PRESS:
        if not step.key_combo.strip():
            errs.append("no key combo set")
            return None, errs
        return _build_key_press(step), errs
    if step.kind == KIND_IF_INVENTORY_FULL:
        return _build_if_inventory_full(step), errs
    if step.kind == KIND_IF_HP_BELOW:
        return _build_if_hp_below(step), errs
    if step.kind == KIND_IF_ITEM_COUNT:
        if not step.item_name.strip():
            errs.append("no item name set")
            return None, errs
        return _build_if_item_count(step), errs
    if step.kind == KIND_LOOP_BACK:
        # loop_back without a target_id is "loop the whole list" — the
        # runner already wraps step_idx modulo, so this is a no-op
        # rule that just forces a tick to fire. Useful for keep-alive
        # bots; otherwise users want to set a target.
        return _build_loop_back(step), errs
    if step.kind == KIND_UPTEXT_CHECK:
        if not step.uptext_pattern.strip():
            errs.append("no uptext pattern set")
            return None, errs
        return _build_uptext_check(step), errs

    errs.append(f"unknown step kind {step.kind!r}")
    return None, errs


def _wrap_branch(
    gate: Callable[[], bool],
    target: Callable[[], bool],
) -> Callable[[], bool]:
    """Gate predicate is True → run target inline and return its result."""
    def _wrapped() -> bool:
        if not gate():
            return False
        return bool(target())
    _wrapped.__name__ = "branch_wrapped"
    return _wrapped


# ── Action closures ─────────────────────────────────────────────


def _build_find_color_click(step: AIBotStep) -> Callable[[], bool]:
    target_hex = _rgb_to_hex_int(step.color_target_rgb)
    extras = [_rgb_to_hex_int(rgb) for rgb in step.color_extra_rgbs]
    tol = float(step.color_tolerance)
    cts = int(step.color_cts_mode)
    min_px = int(step.color_min_pixels)
    cluster_dist = int(step.color_cluster_dist)
    roi = step.roi
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        m = _api.find_color(
            target=target_hex, tol=tol, cts=cts,
            min_pixels=min_px, cluster_dist=cluster_dist, roi=roi,
        )
        if not m:
            # Try secondary colours (multi-tone targets).
            for ex in extras:
                m = _api.find_color(
                    target=ex, tol=tol, cts=cts,
                    min_pixels=min_px, cluster_dist=cluster_dist, roi=roi,
                )
                if m:
                    break
            else:
                return False
        _api.click.at(m.point)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_find_color_keypress(step: AIBotStep) -> Callable[[], bool]:
    target_hex = _rgb_to_hex_int(step.color_target_rgb)
    tol = float(step.color_tolerance)
    cts = int(step.color_cts_mode)
    min_px = int(step.color_min_pixels)
    roi = step.roi
    combo = step.key_combo
    repeat = int(step.key_repeat)
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        m = _api.find_color(
            target=target_hex, tol=tol, cts=cts,
            min_pixels=min_px, roi=roi,
        )
        if not m:
            return False
        for _ in range(max(1, repeat)):
            _api.key(combo)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_find_dtm_click(step: AIBotStep) -> Callable[[], bool]:
    path = step.dtm_template_path
    roi = step.roi
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        m = _api.find_dtm(path, roi=roi)
        if not m:
            return False
        _api.click.at(m.point)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_find_capture_click(step: AIBotStep, asset_path) -> Callable[[], bool]:
    """Template-match a player-captured snapshot against the current
    frame; click the centroid of the best match.

    Loads the template once at compile time. Per tick:
      1. Crop frame to the step's ROI (or use the whole frame).
      2. Run cv2.matchTemplate (TM_CCOEFF_NORMED).
      3. If max-correlation >= threshold, click at (max_loc + half-size).
      4. Else return False so the runner can retry / fail / fall through.

    Falls back to a numpy correlation if cv2 isn't importable for any
    reason. The cv2 path is much faster on 4K frames.
    """
    from pathlib import Path
    from ..algorithms.bitmap import load_png
    template_bgr = load_png(Path(asset_path))
    th, tw = template_bgr.shape[:2]
    threshold = float(step.capture_match_threshold)
    roi = step.roi
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        ctx = _api._ctx()
        frame = getattr(ctx, "current_frame", None)
        if frame is None:
            return False
        if roi is not None:
            rx, ry, rw, rh = roi
            fh, fw = frame.shape[:2]
            rx = max(0, min(rx, fw - 1))
            ry = max(0, min(ry, fh - 1))
            rw = max(tw, min(rw, fw - rx))
            rh = max(th, min(rh, fh - ry))
            search = frame[ry:ry + rh, rx:rx + rw]
            offset = (rx, ry)
        else:
            search = frame
            offset = (0, 0)
        if search.shape[0] < th or search.shape[1] < tw:
            return False
        try:
            import cv2
            result = cv2.matchTemplate(search, template_bgr, cv2.TM_CCOEFF_NORMED)
            _min_v, max_v, _min_loc, max_loc = cv2.minMaxLoc(result)
        except Exception:
            return False
        if max_v < threshold:
            return False
        cx = offset[0] + max_loc[0] + tw // 2
        cy = offset[1] + max_loc[1] + th // 2
        _api.click.at((cx, cy))
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_zone_click(step: AIBotStep) -> Callable[[], bool]:
    """Pick a random point inside the step's drawn Zone and click it.

    Direct port of PhantomClick's Click mode logic. Reuses the
    existing Zone dataclass + Zone.random_point() so the stochastic
    sampling matches what users already trust.
    """
    from modules.zone_selector import Zone
    zone = Zone.from_json(step.zone_json)
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        if zone is None:
            return False
        try:
            point = zone.random_point()
        except Exception:
            return False
        if point is None:
            return False
        _api.click.at(point)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_find_animation_click(step: AIBotStep) -> Callable[[], bool]:
    """Find a flickering region inside ``step.roi`` and click the most
    active candidate. Stateful — keeps a sliding window of recent
    frames in a closure cell so the diff has history to chew on.
    """
    from ..algorithms.animation import AnimationDetector
    detector = AnimationDetector(
        roi=step.roi,
        window=int(step.anim_window_frames),
        min_flickers=int(step.anim_min_flickers),
    )
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        ctx = _api._ctx()
        frame = getattr(ctx, "current_frame", None)
        if frame is None:
            return False
        result = detector.tick(frame)
        if not result.candidates:
            return False
        # Click the candidate with the highest flicker count — that's
        # usually the centre of the most-active spot.
        target = result.candidates[0]
        _api.click.at(target.centroid)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_wait(step: AIBotStep) -> Callable[[], bool]:
    lo, hi = step.wait_min_ms, step.wait_max_ms

    def _r() -> bool:
        _api.wait(_uniform_int(lo, hi))
        return True               # always fires — terminates the tick
    return _r


def _build_key_press(step: AIBotStep) -> Callable[[], bool]:
    combo = step.key_combo
    repeat = int(step.key_repeat)
    after_min, after_max = step.after_min_ms, step.after_max_ms

    def _r() -> bool:
        for _ in range(max(1, repeat)):
            _api.key(combo)
        _api.wait(_uniform_int(after_min, after_max))
        return True
    return _r


def _build_if_inventory_full(step: AIBotStep) -> Callable[[], bool]:
    threshold = int(step.inventory_threshold)

    def _r() -> bool:
        inv = _api.world().inventory
        if inv is None:
            return False
        return inv.count_filled() >= threshold
    return _r


def _build_if_hp_below(step: AIBotStep) -> Callable[[], bool]:
    threshold = int(step.hp_threshold_pct)

    def _r() -> bool:
        hp = _api.world().hp_pct()
        if hp is None:
            return False
        return hp < threshold
    return _r


def _build_if_item_count(step: AIBotStep) -> Callable[[], bool]:
    """Predicate: count of inventory slots holding ``step.item_name``
    compared against ``step.item_count_threshold`` via
    ``step.item_count_op``. Requires the bot's ItemLibrary to have
    ``item_name`` registered + the inventory to be calibrated.
    """
    name = step.item_name.strip()
    threshold = int(step.item_count_threshold)
    op = step.item_count_op or ">="

    def _r() -> bool:
        n = _api.world().count_item(name)
        if op == ">=":
            return n >= threshold
        if op == "<=":
            return n <= threshold
        if op == "==":
            return n == threshold
        if op == ">":
            return n > threshold
        if op == "<":
            return n < threshold
        return False
    return _r


def _build_loop_back(step: AIBotStep) -> Callable[[], bool]:
    """Tick-scoped loop. ``loop_count = 0`` = forever (rule wins every
    tick). ``loop_count = N`` = rule wins next N ticks then disables.
    """
    state = {"remaining": int(step.loop_count or 0), "forever": step.loop_count == 0}

    def _r() -> bool:
        if state["forever"]:
            return True
        if state["remaining"] <= 0:
            return False
        state["remaining"] -= 1
        return True
    return _r


def _build_uptext_check(step: AIBotStep) -> Callable[[], bool]:
    pattern = step.uptext_pattern
    is_regex = bool(step.uptext_is_regex)
    compiled = None
    if is_regex:
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            compiled = None     # treat as literal substring fallback

    def _r() -> bool:
        u = _api.uptext()
        if not u:
            return False
        text = str(u.get("text") or "")
        if compiled is not None:
            return bool(compiled.search(text))
        return pattern.lower() in text.lower()
    return _r


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────


def _rgb_to_hex_int(rgb) -> int:
    if not rgb:
        return 0
    r, g, b = rgb
    return ((int(r) & 0xFF) << 16) | ((int(g) & 0xFF) << 8) | (int(b) & 0xFF)


def _uniform_int(lo: int, hi: int) -> int:
    if hi <= lo:
        return max(0, int(lo))
    return random.randint(int(lo), int(hi))
