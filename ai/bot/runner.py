"""BotRunner — executes a :class:`Bot` on a background QThread and
emits the same Qt signals the graph ``RuntimeController`` does, so
the Studio's Dashboard / LogPanel / Visualizer wire up identically.

Per tick:

1. Capture a frame via mss, set ``ctx.current_frame``.
2. Bind the context via ``contextvars`` so ``find_color`` etc. inside
   rule bodies pick it up implicitly.
3. Walk rules in definition order. First one that returns truthy
   "wins" — subsequent rules skip this tick.
4. Emit ``block_executed`` telemetry per fired rule (same shape as
   graph block_executed so Dashboard phase chip + TaskRuntime's click
   counter keep working).
5. AFK reliability:
   - Track consecutive-no-match ticks; auto-stop at
     ``bot.auto_stop_dry_ticks``.
   - Track last-click time; auto-stop after
     ``bot.watchdog_no_click_s`` seconds with nothing fired.
   - Surface click + detection totals on the health snapshot.
"""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import mss
import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from ..graph.runtime import RuntimeContext
from ..input import get_backend
from . import api
from .bot import Bot


# ─────────────────────────────────────────────────────────────────
# Worker (lives on its own QThread)
# ─────────────────────────────────────────────────────────────────


class _BotWorker(QObject):
    """Drives the tick loop for a :class:`Bot`."""

    log = Signal(str)
    status = Signal(str)
    finished = Signal(str)
    frame_captured = Signal(object)
    block_executed = Signal(object)
    tick_started = Signal(int)

    def __init__(
        self,
        bot: Bot,
        *,
        tick_rate_hz: float,
        default_monitor: int,
        default_roi: Any = None,
        dry_run: bool = False,
        humanizer_config: Any = None,
        actuator: Any = None,
        world_calibration: Optional[dict] = None,
    ) -> None:
        super().__init__()
        self._bot = bot
        self._tick_interval = 1.0 / max(0.5, tick_rate_hz)
        self._default_monitor = int(default_monitor)
        self._default_roi = default_roi
        self._dry_run = bool(dry_run)
        self._humanizer_config = humanizer_config
        # When set, BotRunner uses this pre-built backend instead of
        # constructing one via ``get_backend("real", ...)``. Wired up
        # by the merged PhantomClick app so AI clicks share Clicker's
        # humanization state and AI keystrokes go through the Arduino
        # HID backend (the only NXT-resistant keyboard path).
        self._actuator = actuator
        # User-calibrated ROIs for the awareness layer. Copied onto
        # ctx._world_calibration at startup so WorldState can read it
        # via the contextvars-bound ctx during each tick.
        self._world_calibration: dict = dict(world_calibration or {})
        # Optional per-bot item library — if attached to the Bot via
        # ``bot.item_library``, the runner makes it visible to
        # WorldState. Bots that don't use item identification leave
        # this as None.
        self._item_library: Any = getattr(bot, "item_library", None)
        self._ctx: Optional[RuntimeContext] = None
        self._mss: Any = None
        # Procedural-program runtime state — only used when the bot
        # carries a compiled program (set by ai.bot.compile_program).
        # Lazy-initialized in _run_program_tick on first call.
        self._program_initialized = False
        self._active_proc: str = ""
        self._active_pc: int = 0
        self._call_stack: List[Tuple[str, int]] = []
        self._interrupt_cooldowns: Dict[str, int] = {}
        # Closed-loop verification state. When the active step's
        # verify field is set and the step's closure returned truthy,
        # the runner installs a Verifier here and polls it each tick
        # until success/timeout, then advances or runs on_fail.
        self._pending_verifier: Any = None
        self._pending_verifier_step_label: str = ""
        self._step_retry_count: int = 0
        # Optional bundle reference — when set, failure screenshots
        # land at <bundle.runs_dir>/<session>/failures/. Without one
        # we just skip the screenshot (no place to put it).
        self._bundle: Any = None
        self._failure_dir: Any = None       # lazy-created on first failure
        # Minimap tracker — stateful across ticks (motion-diff needs
        # the previous crop). Pre-loaded with the bundle's run-energy
        # max_fill so percentages are meaningful from the first tick.
        from ..algorithms.minimap import MinimapTracker
        mm_max = int(
            (self._world_calibration.get("orbs_max_fill") or {}).get(
                "run_energy", 0
            ) or 0
        )
        self._minimap_tracker = MinimapTracker(run_energy_max_fill=mm_max)
        # AFK state.
        self._consecutive_dry_ticks = 0
        self._last_click_at: float = 0.0
        self._last_fired_name: Optional[str] = None
        self._last_fired_tick: int = 0
        self._current_tick: int = 0
        # Auto-camera state — burst count resets every time a rule fires.
        self._camera_bursts: int = 0
        # Pause flag (C.2). When True the tick loop skips rule eval, AFK
        # accounting, and verifier ticking — it just sleeps and checks
        # again next pass. Resume re-anchors ``_last_click_at`` so the
        # no-click watchdog doesn't trip on the gap.
        self._paused: bool = False
        self._paused_at: float = 0.0
        # Optional replay source (D.1). When set, ``_capture()`` pulls
        # frames from this iterable instead of mss. None = live capture.
        self._frame_source: Any = None

    # ── live controls ───────────────────────────────────
    def set_tick_rate(self, hz: float) -> None:
        self._tick_interval = 1.0 / max(0.5, float(hz))

    def set_dry_run(self, enabled: bool) -> None:
        self._dry_run = bool(enabled)
        if self._ctx is not None:
            self._ctx.dry_run = self._dry_run

    def stop(self) -> None:
        if self._ctx is not None:
            self._ctx.request_stop("user pressed Stop")

    def pause(self) -> bool:
        """Pause the tick loop. Returns True iff state changed."""
        if self._paused:
            return False
        self._paused = True
        self._paused_at = time.monotonic()
        return True

    def resume(self) -> bool:
        """Resume from pause. Re-anchors AFK timers so the no-click
        watchdog doesn't trip on the paused interval. Returns True iff
        state changed."""
        if not self._paused:
            return False
        gap = max(0.0, time.monotonic() - self._paused_at)
        self._paused = False
        self._paused_at = 0.0
        # Push the no-click watchdog forward by the pause duration so
        # the bot doesn't immediately abort on resume.
        if self._last_click_at > 0.0:
            self._last_click_at += gap
        return True

    def is_paused(self) -> bool:
        return bool(self._paused)

    # ── main loop ───────────────────────────────────────
    def run(self) -> None:
        self.status.emit("Running")

        ctx = RuntimeContext(
            log_fn=lambda m: self.log.emit(m),
            input_backend=None,
            default_monitor=self._default_monitor,
            default_roi=self._default_roi,
            dry_run=self._dry_run,
        )
        if self._actuator is not None:
            backend = self._actuator
        else:
            try:
                backend = get_backend(
                    "real",
                    humanizer_config=self._humanizer_config,
                    is_stopped=ctx.should_stop,
                    on_failsafe=lambda: ctx.request_stop(
                        "corner failsafe — cursor hit screen corner"
                    ),
                )
            except Exception as e:
                self.log.emit(f"[bot] couldn't build input backend: {e}")
                self.finished.emit(f"backend error: {e}")
                return
        ctx.input_backend = backend
        ctx.current_frame = None
        # Hook a click-counter into the context so the AFK watchdog works
        # without patching the backend.
        ctx._bot_click_count = 0
        original_click = backend.click

        def _counting_click(x, y, button="left"):
            ctx._bot_click_count += 1
            self._last_click_at = time.monotonic()
            return original_click(x, y, button=button)

        backend.click = _counting_click  # type: ignore[method-assign]

        self._ctx = ctx
        # Awareness-layer calibration — pulled by WorldState each tick.
        ctx._world_calibration = dict(self._world_calibration)
        # Item library (if any) — exposed to WorldState as ctx.item_library.
        if self._item_library is not None:
            ctx.item_library = self._item_library
        # Chat-event ring buffer + minimap-derived player delta —
        # consumed by on_chat / chat_match / on_player_moved.
        from collections import deque as _deque
        ctx.recent_chat_events = _deque(maxlen=50)
        ctx.player_move_delta_tiles = 0.0
        ctx.minimap_state = None
        self._last_click_at = time.monotonic()
        self._consecutive_dry_ticks = 0

        n_rules = sum(1 for r in self._bot.rules if r.enabled)
        self.log.emit(
            f"[bot] starting {self._bot.name!r} "
            f"({n_rules}/{len(self._bot.rules)} rules, "
            f"tick={int(1/self._tick_interval)} Hz, dry_run={self._dry_run})"
        )

        tick = 0
        try:
            while not ctx.should_stop():
                # Pause gate — skip the entire tick body when paused so
                # AFK accounting, frame capture, and verifier ticking
                # all freeze. Stop is still honoured (the outer
                # should_stop() check above runs first).
                if self._paused:
                    if self._sleep_tick(ctx):
                        break
                    continue
                tick += 1
                self._current_tick = tick
                self.tick_started.emit(tick)
                frame = self._capture()
                if frame is None:
                    if self._sleep_tick(ctx):
                        break
                    continue
                self.frame_captured.emit(np.ascontiguousarray(frame).copy())
                ctx.current_frame = frame
                # Update the stateful minimap tracker (cheap diff vs
                # previous tick) BEFORE WorldState is built — the
                # WorldState reads ctx.minimap_state instead of doing
                # its own scan, so the tracker's previous-frame
                # memory is preserved across ticks.
                mm_rect = (ctx._world_calibration or {}).get("minimap_rect")
                if mm_rect is not None:
                    try:
                        ms = self._minimap_tracker.tick(frame, tuple(mm_rect))
                    except Exception as e:
                        self.log.emit(
                            f"[bot] minimap tick crashed: {type(e).__name__}: {e}"
                        )
                        ms = None
                    if ms is not None:
                        ctx.minimap_state = ms
                        # Trigger feed: the on_player_moved trigger
                        # reads ctx.player_move_delta_tiles directly.
                        ctx.player_move_delta_tiles = ms.motion_tiles
                # Per-tick WorldState — lazy fields cache once each tick.
                from .world import build_world
                ctx.world = build_world(ctx, frame, tick)

                token = api._set_ctx(ctx)
                fired_name = None
                try:
                    if getattr(self._bot, "program", None) is not None:
                        fired_name = self._run_program_tick(ctx, tick)
                    else:
                        fired_name = self._run_legacy_tick(ctx, tick)
                finally:
                    api._reset_ctx(token)

                if fired_name is None:
                    self._consecutive_dry_ticks += 1
                else:
                    self._consecutive_dry_ticks = 0
                    self._camera_bursts = 0  # any successful fire resets

                # Auto-camera fallback: rotate after N dry ticks so a
                # bad camera angle doesn't immediately trip the AFK
                # watchdog. Give up after ``max_bursts`` rotations.
                if (
                    fired_name is None
                    and self._bot.auto_camera
                    and self._bot.auto_camera_dry_ticks > 0
                    and self._consecutive_dry_ticks > 0
                    and self._consecutive_dry_ticks % self._bot.auto_camera_dry_ticks == 0
                    and self._camera_bursts < self._bot.auto_camera_max_bursts
                ):
                    self._camera_bursts += 1
                    step = self._bot.auto_camera_step_deg
                    self.log.emit(
                        f"[auto-camera] dry for {self._consecutive_dry_ticks} ticks — "
                        f"rotating right {step:.0f}° "
                        f"(burst {self._camera_bursts}/{self._bot.auto_camera_max_bursts})"
                    )
                    token = api._set_ctx(ctx)
                    try:
                        # Late import to avoid a bot → camera → api → bot cycle.
                        from . import camera as _camera
                        try:
                            _camera.rotate_right(degrees=step)
                        except Exception as e:
                            self.log.emit(
                                f"[auto-camera] rotate failed: {type(e).__name__}: {e}"
                            )
                    finally:
                        api._reset_ctx(token)

                # AFK watchdogs.
                if (
                    self._bot.auto_stop_dry_ticks > 0
                    and self._consecutive_dry_ticks >= self._bot.auto_stop_dry_ticks
                ):
                    ctx.request_stop(
                        f"AFK watchdog: {self._consecutive_dry_ticks} consecutive "
                        "dry ticks — no rule fired. Check if you got logged out "
                        "or the screen changed."
                    )
                    break
                since_click = time.monotonic() - self._last_click_at
                if (
                    self._bot.watchdog_no_click_s > 0
                    and since_click > self._bot.watchdog_no_click_s
                ):
                    ctx.request_stop(
                        f"AFK watchdog: no click in {since_click:.0f} s "
                        f"(limit {self._bot.watchdog_no_click_s:.0f} s)"
                    )
                    break

                if fired_name is None:
                    if self._sleep_tick(ctx):
                        break
        except Exception as e:
            self.log.emit(
                f"[bot] crashed: {type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            ctx.request_stop(f"exception: {type(e).__name__}: {e}")

        # Backend cleanup.
        try:
            shutdown = getattr(ctx.input_backend, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except Exception as e:
            self.log.emit(f"[bot] backend shutdown failed: {type(e).__name__}: {e}")

        reason = ctx.stop_reason() or "stopped"
        self.log.emit(
            f"[bot] finished after {tick} tick(s): {reason} "
            f"(clicks={ctx._bot_click_count})"
        )
        self.status.emit("Stopped")
        self.finished.emit(reason)

    # ── helpers ──────────────────────────────────────────
    def _capture(self):
        # Replay mode (D.1): if a frame source is wired, pull from it
        # instead of mss. Returning None signals end-of-replay; the
        # outer tick loop treats that as a soft stop reason.
        if self._frame_source is not None:
            try:
                frame = self._frame_source.next_frame()
            except Exception as e:
                self.log.emit(f"[bot] replay source crashed: {type(e).__name__}: {e}")
                return None
            if frame is None:
                # Tell the loop to stop cleanly when the replay ends.
                if self._ctx is not None:
                    self._ctx.request_stop("replay finished")
            return frame
        try:
            if self._mss is None:
                self._mss = mss.mss()
            mons = self._mss.monitors
            idx = self._default_monitor if 0 <= self._default_monitor < len(mons) else 1
            raw = self._mss.grab(mons[idx])
            arr = np.asarray(raw, dtype=np.uint8)[:, :, :3]
            if not arr.flags["C_CONTIGUOUS"]:
                arr = np.ascontiguousarray(arr)
            return arr
        except Exception as e:
            self.log.emit(f"[bot] capture failed: {type(e).__name__}: {e}")
            return None

    def _sleep_tick(self, ctx: RuntimeContext) -> bool:
        target = time.monotonic() + self._tick_interval
        while time.monotonic() < target:
            if ctx.should_stop():
                return True
            time.sleep(min(0.05, target - time.monotonic()))
        return False

    # ── Legacy tick (flat priority list) ────────────────────────
    def _run_legacy_tick(self, ctx: RuntimeContext, tick: int) -> Optional[str]:
        """Walk ``self._bot.rules`` first-match-wins. Returns the name
        of the rule that fired, or ``None``."""
        for rule in self._bot.rules:
            if ctx.should_stop():
                return None
            if not rule.enabled:
                continue
            t0 = time.monotonic()
            try:
                result = rule.func()
            except Exception as e:
                self.log.emit(
                    f"[bot] rule {rule.name!r} crashed: "
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
                )
                ctx.request_stop(f"rule {rule.name} raised {type(e).__name__}")
                return None
            if not result:
                continue
            self._last_fired_name = rule.name
            self._last_fired_tick = tick
            self.block_executed.emit({
                "identifier": f"bot.rule.{rule.name}",
                "node_id": f"rule_{rule.name}",
                "params": {"phase": rule.phase} if rule.phase else {},
                "inputs": {},
                "outputs": {"fired": True, "phase": rule.phase},
                "elapsed_ms": (time.monotonic() - t0) * 1000.0,
            })
            self.log.emit(f"▶ {rule.name} (phase={rule.phase or '-'})")
            return rule.name
        return None

    # ── Program tick (procedures + interrupts) ──────────────────
    def _run_program_tick(self, ctx: RuntimeContext, tick: int) -> Optional[str]:
        """Procedural runtime: execute one step of the active procedure
        unless an interrupt fires. Returns whatever name the dashboard
        should associate with this tick (interrupt name or
        ``proc.step``), or ``None`` when nothing fired."""
        bot = self._bot
        # Lazy init runtime state on first program tick.
        if not self._program_initialized:
            self._active_proc = getattr(bot, "_program_entry", "main")
            self._active_pc = 0
            self._call_stack = []
            self._interrupt_cooldowns = {}
            self._pending_verifier = None
            self._pending_verifier_step_label = ""
            self._step_retry_count = 0
            self._program_initialized = True
            self.log.emit(
                f"[bot] entering procedure {self._active_proc!r}"
            )

        # Pending verification — poll first. While a verifier is in
        # flight, step execution is paused but interrupts still
        # evaluate (HP-low / disconnect handling has to work even
        # mid-verification). Set a flag so the bottom of this method
        # skips step execution if we're still waiting.
        verifying = False
        if self._pending_verifier is not None:
            verdict = None
            try:
                verdict = self._pending_verifier.tick(ctx)
            except Exception as e:
                self.log.emit(
                    f"[bot] verifier crashed: {type(e).__name__}: {e}"
                )
                self._pending_verifier = None
                self._step_retry_count = 0
            if verdict is not None and verdict.success:
                self.log.emit(
                    f"  ✓ verified {self._pending_verifier_step_label!r} "
                    f"via {verdict.signal} ({verdict.elapsed_ticks} ticks)"
                )
                self._pending_verifier = None
                self._pending_verifier_step_label = ""
                self._step_retry_count = 0
                self._active_pc += 1
                return None
            if verdict is not None and verdict.timed_out:
                label = self._pending_verifier_step_label
                signal = self._pending_verifier.signal
                self._pending_verifier = None
                self._pending_verifier_step_label = ""
                self._handle_verification_failure(ctx, label, signal)
                return None
            verifying = self._pending_verifier is not None

        # Decay interrupt cooldowns by 1 per tick.
        if self._interrupt_cooldowns:
            for nm in list(self._interrupt_cooldowns):
                self._interrupt_cooldowns[nm] -= 1
                if self._interrupt_cooldowns[nm] <= 0:
                    del self._interrupt_cooldowns[nm]

        # Evaluate interrupts in declaration order. First non-cooldown
        # trigger that fires wins this tick.
        from .procedures import HANDLER_ABORT
        for intr in getattr(bot, "_compiled_interrupts", []):
            if ctx.should_stop():
                return None
            if intr.name in self._interrupt_cooldowns:
                continue
            try:
                fired = bool(intr.trigger())
            except Exception as e:
                self.log.emit(
                    f"[bot] interrupt {intr.name!r} crashed: "
                    f"{type(e).__name__}: {e}"
                )
                continue
            if not fired:
                continue
            # Reset its cooldown so a sticky condition (HP staying
            # low for several ticks) doesn't re-trigger every tick.
            if intr.cooldown_ticks > 0:
                self._interrupt_cooldowns[intr.name] = intr.cooldown_ticks
            if intr.handler == HANDLER_ABORT:
                self.log.emit(f"⚡ interrupt {intr.name!r} → abort")
                ctx.request_stop(f"interrupt {intr.name!r} → abort")
                return f"interrupt:{intr.name}"
            # Push current state, jump to handler.
            self._call_stack.append((self._active_proc, self._active_pc))
            self._active_proc = intr.handler
            self._active_pc = 0
            self.log.emit(f"⚡ interrupt {intr.name!r} → procedure {intr.handler!r}")
            self._last_fired_name = f"interrupt:{intr.name}"
            self._last_fired_tick = tick
            self.block_executed.emit({
                "identifier": f"bot.rule.interrupt:{intr.name}",
                "node_id": f"interrupt_{intr.name}",
                "params": {"handler": intr.handler},
                "inputs": {},
                "outputs": {"fired": True},
                "elapsed_ms": 0.0,
            })
            return f"interrupt:{intr.name}"

        # No interrupt fired. If we're mid-verification, just wait —
        # don't execute another step until the prior action's signal
        # confirms or times out.
        if verifying:
            return None

        # Execute the next step of the active proc.
        compiled_procs: Dict[str, list] = getattr(bot, "_compiled_procedures", {})
        # Normalize the active state: if we're parked at or past the
        # end of a procedure (which can happen when a popped pc lands
        # exactly past the suspended caller's last step), pop / restart
        # repeatedly until pc is inside the procedure. Keeps the tick
        # productive instead of wasting it on a "phantom" pc.
        for _ in range(8):           # bounded so a malformed program can't loop
            proc_steps = compiled_procs.get(self._active_proc, [])
            if self._active_pc < len(proc_steps):
                break
            if self._call_stack:
                self._active_proc, prev_pc = self._call_stack.pop()
                self._active_pc = prev_pc + 1
                self.log.emit(
                    f"↩ resuming procedure {self._active_proc!r} at step {self._active_pc}"
                )
                continue
            entry = getattr(bot, "_program_entry", "main")
            if self._active_proc != entry:
                self._active_proc = entry
            self._active_pc = 0
            self.log.emit(f"↻ restarting entry procedure {self._active_proc!r}")
            break
        else:
            # 8 normalizations and we're still past the end — bail.
            ctx.request_stop(
                f"runaway procedure normalization in {self._active_proc!r}"
            )
            return None
        proc_steps = compiled_procs.get(self._active_proc, [])
        if self._active_pc >= len(proc_steps):
            # Couldn't find anything to do (entry is empty). Stop.
            ctx.request_stop(
                f"entry procedure {self._active_proc!r} has no enabled steps"
            )
            return None

        step = proc_steps[self._active_pc]
        if not step.enabled:
            self._active_pc += 1
            return None
        t0 = time.monotonic()
        try:
            result = step.func()
        except Exception as e:
            label = f"{self._active_proc}.{step.name}"
            self.log.emit(
                f"[bot] step {label!r} crashed: "
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
            self._save_failure_artifact(
                ctx, label, f"step crashed: {type(e).__name__}: {e}",
            )
            ctx.request_stop(
                f"step {label} raised {type(e).__name__}"
            )
            return None
        rule_label = f"{self._active_proc}.{step.name}"
        if not result:
            return None              # step didn't satisfy — retry next tick
        self._last_fired_name = rule_label
        self._last_fired_tick = tick
        self.block_executed.emit({
            "identifier": f"bot.rule.{rule_label}",
            "node_id": f"rule_{rule_label}",
            "params": {"phase": step.phase} if step.phase else {},
            "inputs": {},
            "outputs": {"fired": True, "phase": step.phase},
            "elapsed_ms": (time.monotonic() - t0) * 1000.0,
        })
        self.log.emit(f"▶ {rule_label}")

        # Install a verifier if the step asked for one. The pc is NOT
        # advanced yet — we'll advance only after the verifier confirms
        # success on a later tick. ``verify_spec`` is the raw JSON dict
        # captured at compile time.
        spec = getattr(step, "verify_spec", None)
        if spec:
            from ..algorithms.verify import from_json as _verify_from_json
            try:
                v = _verify_from_json(spec, tick_rate_hz=1.0 / max(0.001, self._tick_interval))
            except Exception as e:
                self.log.emit(
                    f"[bot] verify spec rejected for {rule_label!r}: {e}"
                )
                v = None
            if v is not None:
                self._pending_verifier = v
                self._pending_verifier_step_label = rule_label
                self.log.emit(
                    f"  ↳ verifying via {v.signal} (≤ {v.timeout_ticks} ticks)"
                )
                return rule_label

        # No verification — advance immediately.
        self._active_pc += 1
        return rule_label

    def _save_failure_artifact(
        self, ctx: RuntimeContext, label: str, reason: str,
    ) -> None:
        """Write the current frame + a small JSON of ctx state to
        ``<bundle>/runs/<session>/failures/`` so failures at 4 AM can
        be diagnosed in the morning. No-op when no bundle is attached
        (legacy / library bot path)."""
        bundle = self._bundle
        if bundle is None:
            return
        try:
            import time as _time
            from pathlib import Path
            from PIL import Image
            import numpy as np
            import json
            import traceback

            if self._failure_dir is None:
                ts = _time.strftime("%Y-%m-%d_%H-%M-%S")
                self._failure_dir = bundle.runs_dir / ts / "failures"
                self._failure_dir.mkdir(parents=True, exist_ok=True)

            stamp = _time.strftime("%H-%M-%S")
            slug = "".join(
                c if c.isalnum() else "_" for c in (label or "step")
            ).strip("_")[:40] or "step"
            base = self._failure_dir / f"{stamp}_{slug}"

            frame = getattr(ctx, "current_frame", None)
            if frame is not None and isinstance(frame, np.ndarray) and frame.ndim == 3:
                rgb = np.ascontiguousarray(frame[..., ::-1])
                Image.fromarray(rgb).save(str(base.with_suffix(".png")))

            info = {
                "timestamp": _time.time(),
                "label": label,
                "reason": reason,
                "active_proc": self._active_proc,
                "active_pc": self._active_pc,
                "call_stack": list(self._call_stack),
                "retry_count": int(self._step_retry_count),
                "stop_reason": ctx.stop_reason() or "",
            }
            base.with_suffix(".json").write_text(
                json.dumps(info, indent=2), encoding="utf-8",
            )
            self.log.emit(
                f"  📸 failure artifact: {base.name}.png/.json"
            )
        except Exception as e:
            self.log.emit(
                f"[bot] couldn't save failure artifact: "
                f"{type(e).__name__}: {e}"
            )

    def _handle_verification_failure(
        self, ctx: RuntimeContext, step_label: str, signal: str,
    ) -> None:
        """Apply the active step's ``on_fail`` policy.

        Strategy ``"retry"`` (default): bump the retry counter; if the
        budget is exhausted, escalate to abort. ``"abort"``: stop the
        bot. ``"goto_procedure:<name>"``: push current state and run
        the named procedure.
        """
        bot = self._bot
        compiled_procs = getattr(bot, "_compiled_procedures", {})
        proc_steps = compiled_procs.get(self._active_proc, [])
        step = (
            proc_steps[self._active_pc]
            if 0 <= self._active_pc < len(proc_steps) else None
        )
        on_fail = getattr(step, "on_fail", "retry") if step is not None else "retry"
        budget = getattr(step, "retry_budget", 3) if step is not None else 3

        self.log.emit(
            f"  ✗ verification timed out for {step_label!r} "
            f"(signal={signal})  policy={on_fail}"
        )

        if on_fail == "abort":
            self._save_failure_artifact(
                ctx, step_label, f"verify timeout signal={signal} → abort",
            )
            ctx.request_stop(f"verification timeout: {step_label}")
            return

        if on_fail.startswith("goto_procedure:"):
            target = on_fail.split(":", 1)[1].strip()
            if target and target in compiled_procs:
                self._save_failure_artifact(
                    ctx, step_label,
                    f"verify timeout signal={signal} → goto {target}",
                )
                self._call_stack.append((self._active_proc, self._active_pc))
                self._active_proc = target
                self._active_pc = 0
                self._step_retry_count = 0
                self.log.emit(
                    f"  ↪ on_fail → procedure {target!r}"
                )
                return
            self._save_failure_artifact(
                ctx, step_label,
                f"verify timeout — handler {target!r} not found",
            )
            self.log.emit(
                f"  ⚠ on_fail target {target!r} not found; aborting"
            )
            ctx.request_stop(f"verification fail handler missing: {target}")
            return

        # "retry" (default). Bump the counter; on overflow, escalate.
        self._step_retry_count += 1
        if self._step_retry_count >= max(1, int(budget)):
            self._save_failure_artifact(
                ctx, step_label,
                f"verify timeout signal={signal} — retry budget {budget} exhausted",
            )
            self.log.emit(
                f"  ⚠ retry budget exhausted ({budget}) — aborting step"
            )
            ctx.request_stop(
                f"step {step_label!r} exhausted retry budget"
            )
            return
        # Re-run the step on the next tick (don't advance pc).
        self.log.emit(
            f"  ↻ retry {self._step_retry_count}/{budget}"
        )


# ─────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────


class BotRunner(QObject):
    """Qt-signal peer of :class:`RuntimeController` for bot scripts."""

    log = Signal(str)
    status = Signal(str)
    finished = Signal(str)
    frame_captured = Signal(object)
    block_executed = Signal(object)
    tick_started = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._thread: Optional[QThread] = None
        self._worker: Optional[_BotWorker] = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def play(
        self,
        bot: Bot,
        *,
        tick_rate_hz: float = 5.0,
        default_monitor: int = 1,
        default_roi=None,
        dry_run: bool = False,
        humanizer_config=None,
        actuator=None,
        world_calibration: Optional[dict] = None,
        bundle: Any = None,
    ) -> None:
        if self.is_running():
            self.log.emit("[bot] already running — stop first.")
            return
        self._thread = QThread()
        # Merge bot-level humanizer overrides into the Studio config.
        cfg = humanizer_config
        if cfg is not None and bot.humanizer_overrides:
            cfg = cfg.with_overrides(bot.humanizer_overrides)
        self._worker = _BotWorker(
            bot,
            tick_rate_hz=tick_rate_hz,
            default_monitor=default_monitor,
            default_roi=default_roi,
            dry_run=dry_run,
            humanizer_config=cfg,
            actuator=actuator,
            world_calibration=world_calibration,
        )
        # Hand the worker the bundle reference so failure
        # screenshots have a place to land.
        self._worker._bundle = bundle
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(lambda s: self.log.emit(s))
        self._worker.status.connect(lambda s: self.status.emit(s))
        self._worker.finished.connect(self._on_finished)
        self._worker.frame_captured.connect(lambda f: self.frame_captured.emit(f))
        self._worker.block_executed.connect(lambda d: self.block_executed.emit(d))
        self._worker.tick_started.connect(lambda t: self.tick_started.emit(t))
        self._thread.start()

    def play_replay(
        self,
        bot: Bot,
        replay_path: str,
        *,
        loop: bool = False,
        tick_rate_hz: float = 5.0,
        actuator: Any = None,
        humanizer_config: Any = None,
        world_calibration: Optional[dict] = None,
        bundle: Any = None,
    ) -> None:
        """Run ``bot`` against frames pulled from ``replay_path``.

        The replay source replaces live ``mss`` capture — bot rules
        evaluate the saved frames as if they were real, dispatching
        clicks through the actuator (which still goes through the
        humanizer + cursor moves on the real screen, useful for
        smoke-testing the engine without the game running).

        End of replay is treated as a clean session stop (``stop_reason
        = "replay finished"``).
        """
        from .replay import FrameReplay
        if self.is_running():
            self.log.emit("[bot] already running — stop first.")
            return
        source = FrameReplay(replay_path, loop=bool(loop))
        # Force dry_run so the actuator doesn't fire real input on
        # frames the user is just iterating against. Replay's value is
        # detection tuning, not action playback.
        self._thread = QThread()
        cfg = humanizer_config
        if cfg is not None and bot.humanizer_overrides:
            cfg = cfg.with_overrides(bot.humanizer_overrides)
        self._worker = _BotWorker(
            bot,
            tick_rate_hz=tick_rate_hz,
            default_monitor=1,
            default_roi=None,
            dry_run=True,
            humanizer_config=cfg,
            actuator=actuator,
            world_calibration=world_calibration,
        )
        self._worker._bundle = bundle
        self._worker._frame_source = source
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(lambda s: self.log.emit(s))
        self._worker.status.connect(lambda s: self.status.emit(s))
        self._worker.finished.connect(self._on_finished)
        self._worker.frame_captured.connect(lambda f: self.frame_captured.emit(f))
        self._worker.block_executed.connect(lambda d: self.block_executed.emit(d))
        self._worker.tick_started.connect(lambda t: self.tick_started.emit(t))
        self._thread.start()

    def stop(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def pause(self) -> bool:
        """Pause the running bot. No-op when no bot is running."""
        if self._worker is None or not self.is_running():
            return False
        return self._worker.pause()

    def resume(self) -> bool:
        """Resume a paused bot. No-op when not paused."""
        if self._worker is None or not self.is_running():
            return False
        return self._worker.resume()

    def is_paused(self) -> bool:
        if self._worker is None:
            return False
        return bool(self._worker.is_paused())

    def toggle_pause(self) -> Optional[bool]:
        """Flip pause state. Returns the new ``is_paused`` value, or
        None if no bot is running."""
        if self._worker is None or not self.is_running():
            return None
        if self._worker.is_paused():
            self._worker.resume()
            return False
        else:
            self._worker.pause()
            return True

    def set_tick_rate(self, hz: float) -> None:
        if self._worker is not None:
            self._worker.set_tick_rate(hz)

    def set_dry_run(self, enabled: bool) -> None:
        if self._worker is not None:
            self._worker.set_dry_run(enabled)

    def last_fired(self) -> dict:
        w = self._worker
        last_click_at = float(getattr(w, "_last_click_at", 0.0) or 0.0)
        click_count = 0
        if w is not None and getattr(w, "_ctx", None) is not None:
            click_count = int(getattr(w._ctx, "_bot_click_count", 0) or 0)
        no_click_age_s = 0.0
        if last_click_at > 0.0:
            no_click_age_s = max(0.0, time.monotonic() - last_click_at)
        return {
            "running": self.is_running(),
            "last_fired_rule": getattr(w, "_last_fired_name", None),
            "last_fired_tick": int(getattr(w, "_last_fired_tick", 0) or 0),
            "current_tick": int(getattr(w, "_current_tick", 0) or 0),
            "consecutive_dry_ticks": int(getattr(w, "_consecutive_dry_ticks", 0) or 0),
            "click_count": click_count,
            "no_click_age_s": no_click_age_s,
        }

    def current_step_info(self) -> Optional[dict]:
        """Return the active procedural step's display metadata for the
        BotOverlay HUD, or ``None`` when no program is running.

        Shape: ``{"proc": str, "pc": int, "name": str, "kind": str,
        "roi": (x1, y1, x2, y2) | None}``.
        """
        w = self._worker
        if w is None or not self.is_running():
            return None
        bot = getattr(w, "_bot", None)
        if bot is None or getattr(bot, "program", None) is None:
            return None
        proc_name = str(getattr(w, "_active_proc", "") or "")
        pc = int(getattr(w, "_active_pc", 0) or 0)
        compiled_procs = getattr(bot, "_compiled_procedures", {}) or {}
        steps = compiled_procs.get(proc_name) or []
        if not (0 <= pc < len(steps)):
            return {"proc": proc_name, "pc": pc, "name": "",
                    "kind": "", "roi": None}
        step = steps[pc]
        return {
            "proc": proc_name,
            "pc": pc,
            "name": getattr(step, "name", ""),
            "kind": getattr(step, "kind", ""),
            "roi": getattr(step, "roi", None),
        }

    def _on_finished(self, reason: str) -> None:
        self.finished.emit(reason)
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
            self._thread = None
            self._worker = None


# ─────────────────────────────────────────────────────────────────
# Standalone run (``python my_bot.py``)
# ─────────────────────────────────────────────────────────────────


def standalone_run(bot: Bot) -> None:
    """Minimal tick loop for running a bot without the Studio.

    No Qt, no signals. Prints log lines to stdout. Respects
    Ctrl+C to shut down cleanly.
    """
    import signal as _signal
    from ..humanize.config import HumanizerConfig

    cfg = HumanizerConfig().with_overrides(bot.humanizer_overrides) if bot.humanizer_overrides else HumanizerConfig()
    monitor = bot.monitor if bot.monitor is not None else 1

    print(f"[bot] standalone run: {bot.name!r}  "
          f"rules={len(bot.rules)}  tick={bot.tick_rate_hz} Hz  dry_run={bot.dry_run}")

    ctx = RuntimeContext(
        log_fn=lambda m: print(m),
        input_backend=None,
        default_monitor=monitor,
        default_roi=None,
        dry_run=bot.dry_run,
    )
    try:
        backend = get_backend(
            "real", humanizer_config=cfg,
            is_stopped=ctx.should_stop,
            on_failsafe=lambda: ctx.request_stop("corner failsafe"),
        )
    except Exception as e:
        print(f"[bot] backend build failed: {e}")
        return
    ctx.input_backend = backend

    _sct = mss.mss()
    mons = _sct.monitors
    idx = monitor if 0 <= monitor < len(mons) else 1
    tick = 0

    # Ctrl+C → graceful stop.
    def _sigint(_signum, _frame):
        ctx.request_stop("Ctrl+C")

    try:
        _signal.signal(_signal.SIGINT, _sigint)
    except Exception:
        pass

    interval = 1.0 / max(0.5, bot.tick_rate_hz)
    # Standalone runs have no calibration UI; WorldState fields will
    # all return None (and log a missing-calibration warning once
    # each). Bots designed for the GUI may want to fall back gracefully.
    ctx._world_calibration = {}
    try:
        while not ctx.should_stop():
            tick += 1
            try:
                raw = _sct.grab(mons[idx])
                frame = np.ascontiguousarray(np.asarray(raw, dtype=np.uint8)[:, :, :3])
            except Exception as e:
                print(f"[capture] failed: {e}")
                time.sleep(interval)
                continue
            ctx.current_frame = frame
            from .world import build_world
            ctx.world = build_world(ctx, frame, tick)
            token = api._set_ctx(ctx)
            fired = False
            try:
                for rule in bot.rules:
                    if ctx.should_stop():
                        break
                    if not rule.enabled:
                        continue
                    try:
                        if rule.func():
                            fired = True
                            break
                    except Exception as e:
                        print(f"[bot] rule {rule.name!r} raised {type(e).__name__}: {e}")
                        ctx.request_stop(f"rule error: {e}")
                        break
            finally:
                api._reset_ctx(token)
            if not fired:
                deadline = time.monotonic() + interval
                while time.monotonic() < deadline:
                    if ctx.should_stop():
                        break
                    time.sleep(min(0.05, deadline - time.monotonic()))
    finally:
        try:
            if hasattr(backend, "shutdown"):
                backend.shutdown()
        except Exception:
            pass
        print(f"[bot] stopped after {tick} tick(s): {ctx.stop_reason() or 'idle'}")
