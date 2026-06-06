"""Top-level API functions used inside ``@bot.rule`` bodies.

Every primitive pulls the "current execution context" from a
:class:`contextvars.ContextVar` set by the :class:`BotRunner` each
tick. Inside a ``@bot.rule`` body you just call ``find_color(...)``
or ``click.at(...)`` — the context is implicit.

The primitives dispatch to the existing graph blocks to avoid
duplicating detection logic — one source of truth per primitive,
shared between graphs and bots.
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


_current_ctx: contextvars.ContextVar = contextvars.ContextVar("bot_ctx")


def _ctx():
    """Return the active :class:`RuntimeContext` or raise if called outside a tick."""
    try:
        return _current_ctx.get()
    except LookupError as e:
        raise RuntimeError(
            "bot primitive called outside a @bot.rule body — the runtime "
            "context is only set during bot.run()."
        ) from e


def _set_ctx(ctx):
    """Used by BotRunner to bind the per-tick context."""
    return _current_ctx.set(ctx)


def _reset_ctx(token) -> None:
    _current_ctx.reset(token)


def world():
    """Return the current tick's :class:`WorldState`.

    Only valid inside a ``@bot.rule`` body — the runner attaches a
    fresh ``WorldState`` to ``ctx.world`` at the start of every tick.
    Reading ``world().inventory`` or ``world().orbs`` triggers a
    lazy scan; subsequent reads in the same tick return the cached
    result. Properties return ``None`` when the user hasn't calibrated
    the corresponding ROI yet.
    """
    ctx = _ctx()
    w = getattr(ctx, "world", None)
    if w is None:
        # Defensive — should never trip in practice because the runner
        # builds WorldState before binding the contextvars context.
        from .world import build_world
        frame = getattr(ctx, "current_frame", None)
        if frame is None:
            raise RuntimeError(
                "world() called before frame capture — should be unreachable."
            )
        w = build_world(ctx, frame, tick=0)
        ctx.world = w
    return w


# ─────────────────────────────────────────────────────────────────
# Match — the result of a detection primitive
# ─────────────────────────────────────────────────────────────────


@dataclass
class Match:
    """Return value of :func:`find_color` / :func:`find_dtm` / etc.

    Truthy when a detection succeeded, falsy via ``__bool__`` when not.
    Attribute access: ``.point``, ``.count``, ``.confidence``,
    ``.points`` (list of all clusters / matches), ``.extra`` (misc).
    """

    point: Optional[Tuple[int, int]] = None
    count: int = 0
    confidence: float = 1.0
    points: List[Tuple[int, int]] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.point is not None or self.count > 0


# ─────────────────────────────────────────────────────────────────
# Detection primitives — dispatch to existing graph blocks
# ─────────────────────────────────────────────────────────────────


def _coerce_roi(roi):
    """Playbook-style tuples + strings both accepted."""
    if roi is None or roi == "":
        return ""
    if isinstance(roi, (list, tuple)) and len(roi) == 4:
        return ",".join(str(int(v)) for v in roi)
    return str(roi)


def _call_block(identifier: str, *, frame=None, **params) -> Dict[str, Any]:
    from ..graph.blocks import REGISTRY
    cls = REGISTRY.get(identifier)
    if cls is None:
        _ctx().log(f"[bot] block {identifier!r} not in REGISTRY")
        return {}
    block = cls()
    ctx = _ctx()
    if frame is None:
        frame = ctx.current_frame if hasattr(ctx, "current_frame") else None
    return block.execute(ctx, frame=frame, **params) or {}


def find_color(
    target,
    *,
    tol: float = 20.0,
    cts: int = 2,
    min_pixels: int = 5,
    roi=None,
    cluster_dist: int = 4,
) -> Match:
    """Find the largest matching cluster of a given colour.

    Returns a :class:`Match` (falsy on miss). Uses CTS mode 2 (HSL) by
    default — robust to most antialiasing.
    """
    result = _call_block(
        "color.find",
        target=target,
        cts=cts,
        tol=float(tol),
        roi=_coerce_roi(roi),
        cluster_dist=int(cluster_dist),
        min_cluster_size=int(min_pixels),
    )
    if not result.get("found"):
        return Match()
    point = result.get("point")
    return Match(
        point=point,
        count=int(result.get("count") or 0),
        points=[point] if point else [],
    )


def color_cluster(
    target,
    *,
    tol: float = 20.0,
    cts: int = 2,
    min_pixels: int = 50,
    roi=None,
) -> Match:
    """Threshold-style detection: True when ≥ ``min_pixels`` matching pixels exist.

    Unlike :func:`find_color` which returns a centroid, this cares
    only about "is enough of this colour present in the ROI?". Great
    for inventory-full checks.
    """
    m = find_color(target=target, tol=tol, cts=cts, min_pixels=min_pixels, roi=roi)
    return m  # same Match shape; the min_pixels gate is already applied


_CONTRAST_CYAN_SLUG = "contrast_cyan"
_CONTRAST_RED_SLUG = "contrast_red"


def find_interactable(
    roi=None,
    *,
    color=None,
    tol: float = 25.0,
    min_pixels: int = 30,
    cluster_dist: int = 6,
    debug_label: str = "",
) -> Match:
    """Find the largest cyan-coloured cluster inside ``roi`` — designed
    for RS3's "high contrast" mode where every interactable object
    (fishing spots, trees, bank chests, NPCs, ground items, …) is
    rendered in the same saturated cyan and everything else is greyscale.

    With contrast mode on, this primitive replaces:
    - ``find_animation`` for spots (no flicker tracking needed, cyan
      is uniquely localised already).
    - ``find_dtm`` for chests / NPCs (one stable colour beats a
      multi-point template).
    - ``find_any_color`` with hand-tuned palette samples (the contrast
      cyan is one colour across every interactable so multi-sample
      coverage is built-in).

    The default colour comes from the global captures library's
    ``contrast_cyan`` multi-sample stack — capture it once via the
    Colour label tool, promote globally, and every bot inherits the
    detection. Override with an explicit ``color=0xRRGGBB`` to test
    or to handle a contrast palette that drifts in a future game patch.

    Returns the same :class:`Match` shape as :func:`find_color` —
    ``.point`` is the cluster centroid, ``.count`` is its pixel count.
    """
    if color is None:
        try:
            from ai.captures import colors as _colors
            samples = _colors(_CONTRAST_CYAN_SLUG)
        except KeyError:
            _warn_once(
                _ctx(),
                "contrast_cyan_missing",
                "[bot] find_interactable: no 'contrast_cyan' colour in "
                "the global library. Capture it via the AI tab's Colour "
                "label tool (3-5 samples across cyan interactables) and "
                "promote to global. Falling through with no match.",
            )
            return Match()
        return find_any_color(
            samples,
            tol=tol, cts=2, min_pixels=min_pixels,
            roi=roi, cluster_dist=cluster_dist,
            debug_label=debug_label,
        )
    m = find_color(
        target=color, tol=tol, cts=2, min_pixels=min_pixels,
        roi=roi, cluster_dist=cluster_dist,
    )
    if debug_label:
        try:
            from utils.logger import get_logger
            get_logger().info(
                "[find_interactable/%s] explicit color=0x%06X tol=%.1f "
                "min_px=%d → matched=%s count=%d point=%s",
                debug_label, int(color), float(tol), int(min_pixels),
                bool(m), int(m.count) if m else 0,
                m.point if m else None,
            )
        except Exception:
            pass
    return m


def find_player(
    roi=None,
    *,
    color=None,
    tol: float = 25.0,
    min_pixels: int = 100,
    cluster_dist: int = 8,
) -> Match:
    """Find the player on screen — the largest red-coloured cluster.

    Designed for RS3 contrast mode where the player avatar (and only
    the player) renders in saturated red. Use this to locate the
    player position dynamically — no fixed PLAYER_ROI needed; bots
    track the player wherever the camera pans.

    Default colour comes from the global ``contrast_red`` multi-sample
    capture. Override with ``color=0xRRGGBB`` for tests.

    Returns a :class:`Match` with ``.point`` = centroid (screen-px)
    and ``.count`` = red-pixel count of the largest cluster. The
    pixel count fluctuates while animating (rod swing changes the
    avatar sprite bbox) — :func:`player_is_animating` uses that.
    """
    if color is None:
        try:
            from ai.captures import colors as _colors
            samples = _colors(_CONTRAST_RED_SLUG)
        except KeyError:
            _warn_once(
                _ctx(),
                "contrast_red_missing",
                "[bot] find_player: no 'contrast_red' colour in the "
                "global library. Capture it via the AI tab's Colour "
                "label tool (3-5 samples on your avatar) and promote "
                "to global. Falling through with no match.",
            )
            return Match()
        return find_any_color(
            samples,
            tol=tol, cts=2, min_pixels=min_pixels,
            roi=roi, cluster_dist=cluster_dist,
        )
    return find_color(
        target=color, tol=tol, cts=2, min_pixels=min_pixels,
        roi=roi, cluster_dist=cluster_dist,
    )


def player_is_animating(
    *,
    history: int = 4,
    pos_tol_px: int = 8,
    size_tol_pct: float = 15.0,
) -> bool:
    """Return True iff the player's red blob is moving or changing
    across the recent tick history.

    Calls :func:`find_player` every tick and pushes ``(cx, cy, count)``
    onto a per-bot-context ring buffer. When the buffer is full
    (``history`` ticks deep), checks variance:

    - Centroid range across the window > ``pos_tol_px`` → animating
      (the player is walking or being repositioned by a click).
    - Pixel count range > ``size_tol_pct`` % of the minimum →
      animating (the avatar sprite is cycling — rod swing, attack
      anim, etc).

    Returns False during the warm-up window (first ``history`` ticks
    after bot.start()) — not enough data to compare yet. Bots that
    need this should either accept a 2-second false-idle warm-up or
    gate on a separate "running for at least N ticks" check.

    Replaces the recording-based ``is_animating_recording`` for
    contrast-mode bots: works regardless of camera pan because the
    red colour is invariant.
    """
    ctx = _ctx()
    from collections import deque
    hist = getattr(ctx, "_player_history", None)
    h_int = max(2, int(history))
    if hist is None or hist.maxlen != h_int:
        hist = deque(maxlen=h_int)
        ctx._player_history = hist
    m = find_player()
    if m and m.point is not None:
        hist.append((int(m.point[0]), int(m.point[1]), int(m.count)))
    if len(hist) < h_int:
        return False                    # warm-up
    pts = list(hist)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    sizes = [p[2] for p in pts]
    pos_range = max(
        max(xs) - min(xs),
        max(ys) - min(ys),
    )
    if pos_range > pos_tol_px:
        return True
    min_size = max(1, min(sizes))
    size_range_pct = 100.0 * (max(sizes) - min_size) / float(min_size)
    return size_range_pct > size_tol_pct


def find_any_color(
    targets,
    *,
    tol: float = 20.0,
    cts: int = 2,
    min_pixels: int = 5,
    roi=None,
    cluster_dist: int = 4,
    debug_label: str = "",
) -> Match:
    """Find the largest cluster of pixels matching ANY of the given colours.

    Each ``targets`` entry is a ``0xRRGGBB`` int. Calls :func:`find_color`
    once per target inside the same ROI, and returns the :class:`Match`
    with the largest pixel count. Falsy when no target matches anywhere.

    Designed for the multi-sample colour capture flow — boon procs,
    anti-aliased UI elements, and gradient targets where one pixel
    sample misses the natural variation in the rendered colour::

        from ai.captures import colors
        from ai.bot import find_any_color, click

        SEREN = colors("seren_spirit_halo")          # 3-5 samples
        m = find_any_color(SEREN, tol=18, roi=POOL_ROI_WIDE)
        if m:
            click.at(m.point)

    Costs N×``find_color``. Don't pass an unbounded list — typically
    3–5 samples is enough.

    Diagnostics: pass ``debug_label="..."`` to log per-sample pixel
    counts + chosen centroid at INFO level. Use this to diagnose
    detection failures — a single log run tells you whether all
    samples missed (palette mismatch), clusters fell below threshold
    (min_pixels too high), or the best match was just in a weird
    place (ROI/cluster_dist issue). Keep ``debug_label`` empty in
    steady-state code so logs don't fill up.
    """
    best = Match()
    log = None
    if debug_label:
        try:
            from utils.logger import get_logger
            log = get_logger()
        except Exception:
            log = None
    scanned = 0
    for t in targets:
        scanned += 1
        m = find_color(
            target=t, tol=tol, cts=cts, min_pixels=min_pixels,
            roi=roi, cluster_dist=cluster_dist,
        )
        if log is not None:
            log.info(
                "[find_any_color/%s] sample=0x%06X tol=%.1f min_px=%d "
                "→ matched=%s count=%d point=%s",
                debug_label, int(t), float(tol), int(min_pixels),
                bool(m), int(m.count) if m else 0,
                m.point if m else None,
            )
        if m and m.count > best.count:
            best = m
    if log is not None:
        log.info(
            "[find_any_color/%s] result: best_count=%d best_point=%s "
            "(%d samples scanned)",
            debug_label, int(best.count), best.point, scanned,
        )
    return best


def find_dtm(template_path: str, *, roi=None, max_matches: int = 5) -> Match:
    """Deformable-template match — YAML template → match point + confidence."""
    result = _call_block(
        "dtm.find",
        template_path=str(template_path),
        roi=_coerce_roi(roi),
        max_matches=int(max_matches),
    )
    if not result.get("found"):
        return Match()
    point = result.get("point")
    return Match(
        point=point,
        count=1,
        confidence=float(result.get("confidence") or 0.0),
        points=[point] if point else [],
        extra={"matches": result.get("matches")},
    )


def find_ocr(
    *,
    font_path: str = "",
    target=0xFFFFFF,
    tol: float = 20.0,
    cts: int = 2,
    roi=None,
    regex: Optional[str] = None,
) -> Match:
    """Bitmap-font OCR — returns match with text content in ``extra['text']``."""
    result = _call_block(
        "ocr.read",
        font_path=str(font_path),
        target=target,
        cts=cts,
        tol=float(tol),
        roi=_coerce_roi(roi),
    )
    text = str(result.get("text") or "")
    line_count = int(result.get("line_count") or 0)
    if line_count == 0:
        return Match()
    if regex:
        import re as _re
        try:
            if _re.search(regex, text) is None:
                return Match()
        except _re.error:
            return Match()
    return Match(
        count=line_count,
        extra={"text": text, "lines": result.get("lines")},
    )


# ─────────────────────────────────────────────────────────────────
# Action primitives
# ─────────────────────────────────────────────────────────────────


class _Click:
    """Callable wrapper — ``click.at(point)`` is the canonical form."""

    def __call__(self, x: int, y: int, button: str = "left") -> None:
        self.at((int(x), int(y)), button=button)

    def at(self, point, button: str = "left") -> None:
        if point is None:
            _ctx().log("[bot] click.at: point is None — skipped")
            return
        x, y = int(point[0]), int(point[1])
        ctx = _ctx()
        if getattr(ctx, "dry_run", False):
            ctx.log(f"🧪 [dry-run] click {button} at ({x}, {y})")
            return
        try:
            ctx.input_backend.click(x, y, button=button)
        except NotImplementedError as e:
            ctx.log(f"[bot] click: backend not ready — {e}")
            ctx.request_stop("input backend not implemented")
            return
        ctx.log(f"click {button} at ({x}, {y})")

    def fire(self, button: str = "left") -> None:
        """Click at the current cursor position WITHOUT re-moving.

        Used after a humanized hover (``move(point)`` + ``wait(...)``)
        when uptext verification has happened — re-moving would shift
        the cursor and possibly miss the just-verified target. The
        humanized ``humanizer.click`` still runs so the mouse-down/up
        cadence stays human; only the bezier travel is skipped.

        Falls back to a fresh ``click.at(current_cursor)`` if the input
        backend doesn't expose ``click_here`` (older actuators) — slower
        but always works.
        """
        ctx = _ctx()
        if getattr(ctx, "dry_run", False):
            ctx.log(f"🧪 [dry-run] click.fire {button} at current cursor")
            return
        backend = ctx.input_backend
        fn = getattr(backend, "click_here", None)
        if callable(fn):
            try:
                fn(button=button)
            except NotImplementedError as e:
                ctx.log(f"[bot] click.fire: backend not ready — {e}")
                return
            ctx.log(f"click.fire {button}")
            return
        # Fallback: ask the OS for the cursor and re-route through click.at.
        try:
            from pynput.mouse import Controller as _MC
            x, y = _MC().position
        except Exception as e:
            ctx.log(f"[bot] click.fire: cursor read failed — {e}")
            return
        self.at((int(x), int(y)), button=button)


click = _Click()


def move(point) -> None:
    if point is None:
        return
    ctx = _ctx()
    x, y = int(point[0]), int(point[1])
    if getattr(ctx, "dry_run", False):
        ctx.log(f"🧪 [dry-run] move to ({x}, {y})")
        return
    try:
        ctx.input_backend.move(x, y)
    except NotImplementedError:
        return


def wait(ms: int) -> None:
    """Sleep for ``ms`` milliseconds, interruptibly."""
    ms = max(0, int(ms))
    if ms == 0:
        return
    ctx = _ctx()
    target = time.monotonic() + ms / 1000.0
    while time.monotonic() < target:
        if ctx.should_stop():
            return
        time.sleep(min(0.05, target - time.monotonic()))


def key(keyname: str) -> None:
    """Press a single key (pyautogui naming: 'space', 'enter', 'f1', 'a', …)."""
    ctx = _ctx()
    if getattr(ctx, "dry_run", False):
        ctx.log(f"🧪 [dry-run] press key {keyname!r}")
        return
    try:
        ctx.input_backend.press_key(keyname)
    except NotImplementedError as e:
        ctx.log(f"[bot] key: backend not ready — {e}")
        return
    ctx.log(f"key press: {keyname!r}")


def log(message: str) -> None:
    """Write a message to the Studio log panel."""
    _ctx().log(str(message))


def stop(reason: str = "stop() called from bot rule") -> None:
    """Halt the bot cleanly."""
    _ctx().request_stop(reason)


# ─────────────────────────────────────────────────────────────────
# Uptext (optional; depends on font availability)
# ─────────────────────────────────────────────────────────────────


def uptext(*, fresh: bool = False) -> Optional[Dict[str, Any]]:
    """Read the RS3 cursor-anchored tooltip.

    Returns ``{'text', 'action', 'target', 'cursor_xy', ...}`` or
    ``None`` if the uptext font isn't built. Failure-silent so bots
    can use ``if (u := uptext()) and "Chop down" in u["text"]: ...``
    without a try/except on every call.

    ``fresh=True`` triggers a brand-new screen capture instead of
    re-reading from the per-tick cached ``ctx.current_frame``. Use this
    after a ``move()`` inside the same rule body — without a fresh
    capture, the still-cached frame won't reflect the tooltip that
    appeared post-hover. Costs ~10–25 ms per call.
    """
    from ..uptext import UptextReader
    ctx = _ctx()
    reader = getattr(ctx, "_uptext_reader", None)
    if reader is None:
        reader = UptextReader()
        ctx._uptext_reader = reader
    if not reader.ready():
        return None
    if fresh:
        snap = reader.read_now()
    else:
        frame = getattr(ctx, "current_frame", None)
        if frame is None:
            return None
        snap = reader.read_from_frame(frame)
    if "error" in snap:
        return None
    return snap


# ─────────────────────────────────────────────────────────────────
# IFTTT primitives — animation, bank-open template match, uptext check
# ─────────────────────────────────────────────────────────────────


def find_animation(
    roi,
    *,
    window: int = 5,
    min_flickers: int = 2,
    tile: int = 8,
) -> Match:
    """Find the strongest pixel-flicker centroid inside ``roi`` as a
    click target.

    Same underlying detector as :func:`is_animating`, but returns the
    centroid of the highest-flicker candidate as ``Match.point`` so
    bots can click directly on it. Falsy when no candidate clears
    ``min_flickers``.

    Use this instead of :func:`find_color` / :func:`find_any_color`
    for animated targets that share a colour palette with their
    background — fishing-spot bubbles vs surrounding water,
    pulsing-trap markers, glowing-ore highlights. Colour matching
    floods on the background; animation matching uniquely localises
    the moving target.

    The detector keeps a ring buffer of recent frames per (roi, window,
    min_flickers, tile) tuple, cached on the bot context. The first
    ``window`` ticks return a falsy match because we need at least 2
    frames to diff — plan a 1–2 tick warm-up after bot.start().
    """
    ctx = _ctx()
    cache = getattr(ctx, "_anim_detectors", None)
    if cache is None:
        cache = {}
        ctx._anim_detectors = cache
    roi_t = tuple(int(v) for v in roi)
    key = (roi_t, int(window), int(min_flickers), int(tile))
    detector = cache.get(key)
    if detector is None:
        from ..algorithms.animation import AnimationDetector
        detector = AnimationDetector(
            roi=roi_t,
            window=window,
            min_flickers=min_flickers,
            tile=tile,
        )
        cache[key] = detector
    frame = getattr(ctx, "current_frame", None)
    if frame is None:
        return Match()
    state = detector.tick(frame)
    if not state.candidates:
        return Match()
    # Highest flicker count = strongest, most-localised animation.
    best = max(state.candidates, key=lambda c: c.flicker_count)
    return Match(
        point=best.centroid,
        count=int(best.flicker_count),
        confidence=1.0,
        points=[c.centroid for c in state.candidates],
        extra={"bbox": best.bbox},
    )


def is_animating(
    roi,
    *,
    window: int = 5,
    min_flickers: int = 2,
    tile: int = 8,
) -> bool:
    """Return True iff pixel-flicker is detected inside ``roi`` over a
    sliding window of recent frames.

    Wraps :class:`ai.algorithms.animation.AnimationDetector`. One
    detector is cached per unique ``(roi, window, min_flickers, tile)``
    on the bot context — the ring buffer needs to persist across ticks
    for the diff to work, so re-creating the detector per call would
    always return False.

    Typical usage in a fishing-style bot::

        @bot.rule(phase="fishing")
        def recast_when_idle():
            if is_animating(PLAYER_ROI):
                return False         # still fishing — leave it alone
            spot = find_color(SPOT_COLOR, roi=POOL_ROI)
            if not spot:
                return False
            click.at(spot.point)
            wait(1500)
            return True

    The first ``window`` ticks return False because the detector needs
    at least 2 frames to diff. Plan for a 1–2 tick warm-up after
    bot.start().
    """
    ctx = _ctx()
    cache = getattr(ctx, "_anim_detectors", None)
    if cache is None:
        cache = {}
        ctx._anim_detectors = cache
    roi_t = tuple(int(v) for v in roi)
    key = (roi_t, int(window), int(min_flickers), int(tile))
    detector = cache.get(key)
    if detector is None:
        from ..algorithms.animation import AnimationDetector
        detector = AnimationDetector(
            roi=roi_t,
            window=window,
            min_flickers=min_flickers,
            tile=tile,
        )
        cache[key] = detector
    frame = getattr(ctx, "current_frame", None)
    if frame is None:
        return False
    state = detector.tick(frame)
    return bool(state.candidates)


def is_animating_recording(
    recording_path,
    *,
    window: int = 5,
    min_flickers: int = 2,
    tile: int = 8,
) -> bool:
    """Animation detection at a ROI resolved from a saved recording.

    Pass a recording directory path (typically from
    :func:`ai.captures.recording`); this helper reads its ``meta.json``,
    extracts the ``rect`` the recording was captured against, and
    delegates to :func:`is_animating` with that ROI. Saves the bot
    writer from manually keeping ROI tuples in sync with their
    recording references.

    Example::

        from ai.captures import recording
        from ai.bot import is_animating_recording

        FISHING_REC = recording("vip_fishing_spot_west")

        @bot.rule(phase="fishing")
        def recast_when_idle():
            if is_animating_recording(FISHING_REC):
                return False  # spot still bubbling
            ...

    Falls back to False (and logs once) if the recording is missing or
    its meta is malformed — better than silently using a wrong ROI.
    """
    from pathlib import Path as _Path
    ctx = _ctx()

    rec_dir = _Path(recording_path)
    if not rec_dir.is_dir():
        _warn_once(ctx, f"recording_dir_missing:{rec_dir}",
                   f"is_animating_recording: directory missing — {rec_dir}")
        return False
    meta_path = rec_dir / "meta.json"
    if not meta_path.exists():
        _warn_once(ctx, f"recording_meta_missing:{rec_dir}",
                   f"is_animating_recording: meta.json missing in {rec_dir}")
        return False
    import json as _json
    try:
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as e:
        _warn_once(ctx, f"recording_meta_bad:{rec_dir}",
                   f"is_animating_recording: meta unreadable — {e}")
        return False
    rect = meta.get("rect")
    if not (isinstance(rect, (list, tuple)) and len(rect) == 4):
        _warn_once(ctx, f"recording_rect_bad:{rec_dir}",
                   f"is_animating_recording: meta.rect malformed in {rec_dir}")
        return False
    return is_animating(
        rect,
        window=window,
        min_flickers=min_flickers,
        tile=tile,
    )


def _warn_once(ctx, key: str, message: str) -> None:
    """Log ``message`` to the bot context exactly once per ``key``.

    Used by helpers that may fail every tick on the same misconfig
    (missing capture, malformed meta) — a single warning is signal,
    a per-tick repeat is noise.
    """
    flag_attr = f"_warned_{abs(hash(key))}"
    if getattr(ctx, flag_attr, False):
        return
    setattr(ctx, flag_attr, True)
    ctx.log(message)


def template_match(
    reference,
    *,
    threshold: float = 0.0,
    roi=None,
) -> Match:
    """Template-match a reference PNG against the current frame.

    Returns a :class:`Match` with ``confidence`` set to the maximum
    correlation score (0.0–1.0) inside the search region. The match
    is falsy when ``confidence < threshold`` (default 0.0 means any
    score counts as a hit — let the caller compare).

    ``reference`` accepts a Path or string path; typically a snapshot
    loaded once at module import::

        from ai.captures import snapshot
        from ai.bot import template_match

        BANK_OPEN_REF = snapshot("bank_open_vip")

        @bot.rule(phase="banking")
        def use_preset():
            m = template_match(BANK_OPEN_REF, threshold=0.85)
            if not m:
                return False
            ...

    ``roi`` restricts the search to a sub-region of the frame
    (physical-px rect). The reference must be smaller than the
    cropped search region.

    Reference images are cached on the bot context keyed by string
    path so repeat calls are free.
    """
    from pathlib import Path as _Path

    ctx = _ctx()
    frame = getattr(ctx, "current_frame", None)
    if frame is None:
        return Match()
    ref_path = _Path(reference) if not isinstance(reference, _Path) else reference
    ref_img = _load_template_cached(ctx, ref_path)
    if ref_img is None:
        return Match()
    score, point = _template_match_impl(ctx, frame, ref_img, roi)
    if score < threshold:
        return Match()
    return Match(
        point=point,
        count=1,
        confidence=float(score),
        points=[point] if point else [],
    )


def tooltip_match(
    reference,
    *,
    threshold: float = 0.75,
    offset: Tuple[int, int] = (2, 14),
    size: Tuple[int, int] = (420, 58),
) -> Match:
    """Template-match against a cursor-anchored ROI — designed for
    verifying the RS3 NXT action tooltip ("Bait fishing spot", "Bank
    chest", "Chop down Willow") is the one expected before clicking.

    The tooltip appears just below + right of the cursor in RS3; this
    helper snapshots that anchor region and runs ``template_match``
    against the saved reference. Same defaults as the legacy
    :class:`UptextReader` (offset (2, 14), size 420×58) — tuned for
    3840×2160 NXT-default UI scale; override if your resolution
    differs significantly.

    Pair with :class:`ai.captures.snapshot` — capture a single
    PNG of the tooltip area while hovering the target in-game, then::

        from ai.captures import snapshot
        from ai.bot import tooltip_match, click, find_animation, move, wait

        SPOT_TOOLTIP = snapshot("vip_spot_tooltip")

        @bot.rule(phase="fishing")
        def recast():
            spot = find_animation(POOL_ROI)
            if not spot: return False
            move(spot.point)
            wait(300)                            # tooltip latency
            if not tooltip_match(SPOT_TOOLTIP):
                return False                     # not over the spot
            click.fire()

    No OCR dependency — works regardless of whether
    ``ai/fonts/plain_11.rvf`` is built.
    """
    from pathlib import Path as _Path

    ctx = _ctx()
    frame = getattr(ctx, "current_frame", None)
    if frame is None:
        return Match()
    ref_path = _Path(reference) if not isinstance(reference, _Path) else reference
    ref_img = _load_template_cached(ctx, ref_path)
    if ref_img is None:
        return Match()

    # Compute cursor-anchored ROI in physical pixels (matches the unit
    # mss / bot ROIs use). Reads the live cursor position rather than
    # any stored value because we want the location the cursor is AT
    # right now — typically just after a humanized move().
    try:
        from pynput.mouse import Controller as _MC
        cx, cy = _MC().position
    except Exception:
        return Match()
    ox, oy = offset
    w, h = size
    roi = (int(cx) + int(ox), int(cy) + int(oy), int(w), int(h))
    score, point = _template_match_impl(ctx, frame, ref_img, roi)
    if score < threshold:
        return Match()
    return Match(
        point=point,
        count=1,
        confidence=float(score),
        points=[point] if point else [],
    )


def _load_template_cached(ctx, ref_path):
    """Load + cache an image template by path. Returns numpy BGR or None."""
    cache = getattr(ctx, "_template_cache", None)
    if cache is None:
        cache = {}
        ctx._template_cache = cache
    key = str(ref_path)
    img = cache.get(key)
    if img is not None:
        return img
    try:
        import cv2 as _cv2
        img = _cv2.imread(str(ref_path), _cv2.IMREAD_COLOR)
    except Exception as e:
        ctx.log(f"[bot] template load failed for {ref_path}: {e}")
        return None
    if img is None:
        ctx.log(f"[bot] template not found / unreadable: {ref_path}")
        return None
    cache[key] = img
    return img


def _template_match_impl(ctx, frame, ref_img, roi):
    """Run cv2.matchTemplate. Returns (max_score, (x, y) of best match)."""
    try:
        import cv2 as _cv2
    except ImportError:
        return 0.0, None
    work = frame
    if work.ndim == 3 and work.shape[2] == 4:
        work = _cv2.cvtColor(work, _cv2.COLOR_BGRA2BGR)
    origin = (0, 0)
    if roi is not None:
        try:
            x, y, w, h = (int(v) for v in roi)
        except Exception:
            return 0.0, None
        fh, fw = work.shape[:2]
        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = max(1, min(w, fw - x))
        h = max(1, min(h, fh - y))
        work = work[y:y + h, x:x + w]
        origin = (x, y)
    rh, rw = ref_img.shape[:2]
    fh, fw = work.shape[:2]
    if rh > fh or rw > fw:
        return 0.0, None
    try:
        result = _cv2.matchTemplate(work, ref_img, _cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, max_l = _cv2.minMaxLoc(result)
    except Exception as e:
        ctx.log(f"[bot] template_match: matchTemplate failed — {e}")
        return 0.0, None
    # max_l is the top-left of the best match in the cropped frame.
    # Convert to centroid in absolute screen coords.
    cx = origin[0] + int(max_l[0]) + rw // 2
    cy = origin[1] + int(max_l[1]) + rh // 2
    return float(max_v), (cx, cy)


def is_bank_open(
    reference,
    *,
    threshold: float = 0.85,
    roi=None,
) -> bool:
    """Return True iff the saved reference snapshot template-matches
    the current frame above ``threshold``.

    ``reference`` accepts a :class:`pathlib.Path` or a string path —
    typically loaded once at module-import time::

        from ai.captures import snapshot
        BANK_OPEN_REF = snapshot("bank_open_vip")

        @bot.rule(phase="banking")
        def use_preset():
            if not is_bank_open(BANK_OPEN_REF):
                return False
            key("1")
            wait(1500)
            return True

    The reference image is loaded once and cached on the bot context
    (keyed by string path). ``cv2.matchTemplate`` runs in
    ``TM_CCOEFF_NORMED`` mode; the default threshold of 0.85 is a
    reasonable starting point for bank-window detection but tune per
    reference if the UI has heavy alpha blending.

    ``roi`` optionally restricts the search to a region of the frame —
    useful when the reference snapshot covers only part of the screen
    and you want to avoid false matches in unrelated UI areas.
    """
    from pathlib import Path as _Path

    ctx = _ctx()
    frame = getattr(ctx, "current_frame", None)
    if frame is None:
        return False

    # Load + cache the reference template.
    cache = getattr(ctx, "_template_cache", None)
    if cache is None:
        cache = {}
        ctx._template_cache = cache
    ref_path = _Path(reference) if not isinstance(reference, _Path) else reference
    cache_key = str(ref_path)
    ref_img = cache.get(cache_key)
    if ref_img is None:
        try:
            import cv2 as _cv2
            ref_img = _cv2.imread(str(ref_path), _cv2.IMREAD_COLOR)
        except Exception as e:
            ctx.log(f"[bot] is_bank_open: cv2 import or imread failed — {e}")
            return False
        if ref_img is None:
            ctx.log(f"[bot] is_bank_open: could not load reference {ref_path}")
            return False
        cache[cache_key] = ref_img

    # Frame channel coercion: BGRA → BGR if the capture has an alpha.
    try:
        import cv2 as _cv2
    except ImportError:
        return False
    work = frame
    if work.ndim == 3 and work.shape[2] == 4:
        work = _cv2.cvtColor(work, _cv2.COLOR_BGRA2BGR)

    if roi is not None:
        try:
            x, y, w, h = (int(v) for v in roi)
        except Exception:
            return False
        fh, fw = work.shape[:2]
        x = max(0, min(x, fw - 1))
        y = max(0, min(y, fh - 1))
        w = max(1, min(w, fw - x))
        h = max(1, min(h, fh - y))
        work = work[y:y + h, x:x + w]

    rh, rw = ref_img.shape[:2]
    fh, fw = work.shape[:2]
    if rh > fh or rw > fw:
        # Reference is larger than the search area — can't possibly match.
        return False

    try:
        result = _cv2.matchTemplate(work, ref_img, _cv2.TM_CCOEFF_NORMED)
        _min_v, max_v, _min_l, _max_l = _cv2.minMaxLoc(result)
    except Exception as e:
        ctx.log(f"[bot] is_bank_open: matchTemplate failed — {e}")
        return False
    return float(max_v) >= float(threshold)


def uptext_matches(
    *,
    action: Optional[str] = None,
    target: Optional[str] = None,
    fresh: bool = True,
    require_font: bool = False,
) -> bool:
    """Return True iff the cursor-anchored tooltip's ``action`` and/or
    ``target`` fields contain the given substrings (case-insensitive).

    Designed for the **hover → uptext-verify → fire** pattern::

        spot = find_color(SPOT_COLOR, roi=POOL_ROI)
        if not spot:
            return False
        move(spot.point)              # humanized hover
        wait(300)                      # in-game tooltip latency
        if not uptext_matches(action="Bait", target="fishing spot"):
            return False               # something else under cursor
        click.fire()
        wait(1500)
        return True

    Defaults to ``fresh=True`` — the typical caller has just hovered
    inside the same tick, and the start-of-tick frame won't reflect
    the post-hover tooltip. Pass ``fresh=False`` to use the cached
    ``world().uptext`` (cheaper, but stale relative to a hover).

    **Font fallback:** uptext OCR needs ``ai/fonts/plain_11.rvf``,
    which is built from a captured RS3 font corpus via
    ``rs3vision-tools/``. When the font isn't on disk this helper
    returns True instead of False — the verification layer is a
    robustness boost, not a hard requirement, and silently failing
    every click would leave the bot stuck. Set ``require_font=True``
    to opt into strict mode for safety-critical clicks (returns
    False when font is missing). A once-per-session warning is
    logged either way so the user knows OCR is offline.
    """
    from ..fonts import uptext_font_ready

    if not uptext_font_ready():
        _warn_once(
            _ctx(),
            "uptext_font_missing",
            "[bot] uptext OCR font is missing (ai/fonts/plain_11.rvf) — "
            "skipping uptext verification. Bot will rely on colour / DTM "
            "match alone. Build the font via rs3vision-tools to re-enable "
            "the safety check.",
        )
        return not require_font
    snap = uptext(fresh=fresh)
    if snap is None:
        return False
    if action is not None:
        a = str(snap.get("action") or "").lower()
        if action.lower() not in a:
            return False
    if target is not None:
        tgt = str(snap.get("target") or "").lower()
        if target.lower() not in tgt:
            return False
    return True
