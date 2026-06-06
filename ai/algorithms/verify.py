"""Action verification — the closed-loop "did the click actually work?"
check that turns "click and hope" into "click, verify, react."

Most action steps in a bot are reactive: they fire when their detection
matches and *assume* the action succeeded. That assumption is wrong
in MMOs all the time — the target moved during the cursor travel,
the click landed on a stale frame, lag swallowed it, the player
animation never started. Without a check, the bot just keeps acting
on a phantom result.

A :class:`Verifier` watches for a specific signal across a short
window of ticks after an action and reports SUCCESS / TIMEOUT. The
runner uses that result to decide whether to advance the program
counter, retry the step, or run a recovery procedure.

Signals shipped here (each cheap per tick):

- ``inv_change`` — the inventory's filled-slot count changed in a
  given direction by a required delta. Best signal for "I just
  caught a fish" or "I just deposited."
- ``uptext_match`` — the cursor-anchored RS3 uptext matches a
  pattern. Confirms the cursor is hovering the expected target
  (e.g. ``"Bank chest"``).
- ``always_pass`` — sentinel that always succeeds on its first
  tick. Useful as a default when a step needs no verification.

The remaining signals from the plan (``player_stillness``,
``chat_match``, ``xp_drop``, ``animation_active``) get added
incrementally as their underlying primitives land. The Verifier API
is forward-compatible: new signal names just register new
``_check_*`` handlers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


# Public verifier signal names — string discriminators in JSON.
SIGNAL_INV_CHANGE = "inv_change"
SIGNAL_UPTEXT_MATCH = "uptext_match"
SIGNAL_CHAT_MATCH = "chat_match"
SIGNAL_PLAYER_STILLNESS = "player_stillness"
SIGNAL_ALWAYS_PASS = "always_pass"

VALID_SIGNALS = (
    SIGNAL_INV_CHANGE,
    SIGNAL_UPTEXT_MATCH,
    SIGNAL_CHAT_MATCH,
    SIGNAL_PLAYER_STILLNESS,
    SIGNAL_ALWAYS_PASS,
)


@dataclass
class VerificationResult:
    """Outcome of a finished verification attempt."""
    success: bool
    timed_out: bool
    elapsed_ticks: int
    signal: str


class Verifier:
    """One pending verification, ticked across multiple frames.

    Construct it right after an action step succeeds. Call
    :meth:`tick` once per bot tick. While waiting, returns ``None``.
    When the signal matches, returns a SUCCESS result; when the
    timeout elapses without a match, returns a TIMEOUT result.

    The Verifier captures any "initial state" it needs for
    diff-based signals (``inv_change``) on its first ``tick`` call,
    not at construction — that way the snapshot reflects the world
    state at the moment we *start* watching, which is the tick
    immediately after the action fired.
    """

    def __init__(
        self,
        signal: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        timeout_ticks: int = 20,
    ) -> None:
        if signal not in VALID_SIGNALS:
            signal = SIGNAL_ALWAYS_PASS
        self.signal = signal
        self.params: Dict[str, Any] = dict(params or {})
        self.timeout_ticks = max(1, int(timeout_ticks))
        self.elapsed = 0
        self._initial: Any = None
        self._initialized = False

    def tick(self, ctx) -> Optional[VerificationResult]:
        if not self._initialized:
            self._initial = self._capture_initial(ctx)
            self._initialized = True
        self.elapsed += 1
        if self._signal_matched(ctx):
            return VerificationResult(
                success=True, timed_out=False,
                elapsed_ticks=self.elapsed, signal=self.signal,
            )
        if self.elapsed >= self.timeout_ticks:
            return VerificationResult(
                success=False, timed_out=True,
                elapsed_ticks=self.elapsed, signal=self.signal,
            )
        return None

    # ── per-signal handlers ─────────────────────────────────────
    def _capture_initial(self, ctx) -> Any:
        if self.signal == SIGNAL_INV_CHANGE:
            inv = getattr(ctx.world, "inventory", None) if ctx.world else None
            return inv.count_filled() if inv is not None else 0
        return None

    def _signal_matched(self, ctx) -> bool:
        sig = self.signal
        if sig == SIGNAL_ALWAYS_PASS:
            return True
        if sig == SIGNAL_INV_CHANGE:
            return self._check_inv_change(ctx)
        if sig == SIGNAL_UPTEXT_MATCH:
            return self._check_uptext_match(ctx)
        if sig == SIGNAL_CHAT_MATCH:
            return self._check_chat_match(ctx)
        if sig == SIGNAL_PLAYER_STILLNESS:
            return self._check_player_stillness(ctx)
        return False

    def _check_inv_change(self, ctx) -> bool:
        inv = getattr(ctx.world, "inventory", None) if ctx.world else None
        if inv is None:
            return False
        current = inv.count_filled()
        initial = int(self._initial or 0)
        delta = max(1, int(self.params.get("delta", 1)))
        direction = str(self.params.get("direction", "increase"))
        if direction == "increase":
            return current >= initial + delta
        if direction == "decrease":
            return current <= initial - delta
        return abs(current - initial) >= delta

    def _check_uptext_match(self, ctx) -> bool:
        from ..bot import api as _api
        u = _api.uptext()
        if not u:
            return False
        text = str(u.get("text") or "")
        pattern = str(self.params.get("pattern") or "")
        if not pattern:
            return False
        if bool(self.params.get("regex", False)):
            try:
                return bool(re.search(pattern, text, re.IGNORECASE))
            except re.error:
                return False
        return pattern.lower() in text.lower()

    def _check_chat_match(self, ctx) -> bool:
        # Wired in B.5 alongside the on_chat interrupt — currently
        # awaits a chat-event source attached to ``ctx``.
        events = getattr(ctx, "recent_chat_events", None)
        if not events:
            return False
        pattern = str(self.params.get("pattern") or "")
        if not pattern:
            return False
        for ev in events:
            txt = str(ev.get("text") or "")
            if pattern.lower() in txt.lower():
                return True
        return False

    def _check_player_stillness(self, ctx) -> bool:
        # Wired alongside minimap reader — currently a stub that
        # never confirms (so steps that require it will time out
        # rather than silently pass with no actual evidence).
        return False


# ─────────────────────────────────────────────────────────────────
# Convenience: build a Verifier from a JSON ``verify`` block
# ─────────────────────────────────────────────────────────────────


def from_json(d: Any, *, tick_rate_hz: float) -> Optional[Verifier]:
    """Build a :class:`Verifier` from a step's ``verify`` field.

    Returns ``None`` when the field is missing/empty (i.e. the step
    doesn't ask for verification). ``timeout_ms`` from the JSON is
    converted to ticks using the bot's ``tick_rate_hz``.
    """
    if not isinstance(d, dict) or not d:
        return None
    signal = str(d.get("signal") or SIGNAL_ALWAYS_PASS)
    if signal not in VALID_SIGNALS:
        signal = SIGNAL_ALWAYS_PASS
    timeout_ms = int(d.get("timeout_ms") or 5000)
    timeout_ticks = max(1, int(round(timeout_ms / 1000.0 * max(0.5, tick_rate_hz))))
    params = dict(d.get("params") or {})
    return Verifier(signal, params=params, timeout_ticks=timeout_ticks)
