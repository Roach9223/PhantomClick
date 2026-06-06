"""KeyTimer: a passive scheduled keypress that runs concurrently with the
main click engine.

A KeyTimer is *not* a step — it doesn't advance recorder state, doesn't
move the cursor, and isn't gated by the active step. It just fires a key
on its own clock so users can do things like "press Z every 6 minutes
for the potion macro" without breaking up their main click sequence.

Each timer runs in its own daemon thread (spawned by Clicker.start()) and
exits when the engine's stop event is set.

Key strings use ``+``-joined lowercase parts: e.g. ``"z"``, ``"f1"``,
``"ctrl+z"``, ``"shift+1"``, ``"ctrl+shift+f5"``. The base (last) part is
the key that's actually pressed; everything before it is held as a
modifier across the press/release.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Optional

from pynput import keyboard

from utils.logger import get_logger

_log = get_logger()


# --- Active key-emission backend ------------------------------------- #
#
# Set by ``Clicker.start()`` based on ``cfg["key_input_method"]``. The
# default SendInput backend is the original behaviour and works in
# every plain Win32 app. Set to an InterceptionBackend instance to
# bypass NXT-style injected-event filters; see ``key_input_backend``.
#
# Late-imported on first set so this module stays cycle-free with
# ``key_input_backend`` (which back-imports us for the SendInput path).
_backend = None


def set_backend(backend) -> None:
    """Engine pushes the chosen backend at session start. ``None`` resets
    to the default SendInput path on next ``fire()``."""
    global _backend
    _backend = backend


def _active_backend():
    """Lazy default — return the SendInput backend when nothing has been
    pushed (ad-hoc callers, tests, KeyTimer threads spawned before the
    engine wired one up)."""
    global _backend
    if _backend is None:
        from . import key_input_backend
        _backend = key_input_backend.SendInputBackend()
    return _backend


# --- Win32 SendInput (scancode mode) ---------------------------------- #
#
# pynput's keyboard.Controller sends keypresses with INPUT.ki.wVk set
# (virtual-key codes). That works fine for plain Win32 apps but Java
# AWT/Swing clients (RuneScape, RuneLite), most DirectInput / RawInput
# games, and some anti-bot filters only react to scancode events. The
# fix is to call SendInput ourselves with KEYEVENTF_SCANCODE flag set,
# wVk=0, and the scancode in wScan — which is what real hardware looks
# like to the input layer. This matches AutoHotkey's default behaviour
# for the same reason.
#
# Implementation: small ctypes shim. Keyboard-only, no mouse path.

import ctypes
from ctypes import wintypes

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

_PUL = ctypes.POINTER(ctypes.c_ulong)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _PUL),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _PUL),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    # Union must include all three so the struct's total size matches the
    # Win32 INPUT shape (the largest member, MOUSEINPUT, dictates size).
    _fields_ = [
        ("ki", _KEYBDINPUT),
        ("mi", _MOUSEINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("ii",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ii", _INPUT_UNION),
    ]


try:
    # CRITICAL: use WinDLL() (constructs a new instance) instead of
    # ctypes.windll.user32 (process-wide singleton). Setting argtypes
    # on the shared singleton mutates the SAME Function object pynput
    # uses internally for its own SendInput calls, which causes pynput
    # to crash with `expected LP__INPUT instance instead of pointer to
    # INPUT` when its mouse press tries to pass its own INPUT struct.
    # WinDLL("user32") gives us a separate _FuncPtr we can configure
    # without disturbing anyone else's bindings.
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype = wintypes.UINT
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype = ctypes.c_short
except Exception:
    _user32 = None  # non-Windows / API unreachable; fire() will log & fail.


# Module-level cache so repeated MapVirtualKey calls per fire are free.
_vk_scan_cache: dict[int, int] = {}


def _vk_to_scan(vk: int) -> int:
    """VK code → keyboard scancode via MapVirtualKeyW, cached per-process."""
    if vk in _vk_scan_cache:
        return _vk_scan_cache[vk]
    if _user32 is None:
        return 0
    scan = int(_user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC))
    _vk_scan_cache[vk] = scan
    return scan


# VKs that Windows considers "extended" — duplicate-position keys (the
# arrow cluster and editing pad as opposed to numpad). Without the
# EXTENDEDKEY flag, sending these scancodes reaches the WRONG physical
# key (e.g. arrow Up vs. numpad 8 share the same scan).
_EXTENDED_VKS = frozenset([
    0x21, 0x22, 0x23, 0x24,  # PRIOR (PageUp), NEXT (PageDown), END, HOME
    0x25, 0x26, 0x27, 0x28,  # LEFT, UP, RIGHT, DOWN
    0x2C, 0x2D, 0x2E,        # SNAPSHOT (PrintScreen), INSERT, DELETE
    0x90,                    # NUMLOCK
])


def _last_sendinput_error() -> int:
    """Wrap GetLastError so callers can log why SendInput rejected an
    event. Returns 0 when ctypes is unavailable."""
    try:
        return int(ctypes.get_last_error())
    except Exception:
        return 0


def _send_scancode(vk: int, key_up: bool) -> bool:
    """Emit one scancode-flagged keyboard event via SendInput. Returns
    True iff Windows accepted (sent==1). Failures are silent at this
    layer; ``fire()`` logs the per-call diagnostic line."""
    if _user32 is None or not vk:
        return False
    scan = _vk_to_scan(vk)
    if scan == 0:
        return False
    flags = KEYEVENTF_SCANCODE
    if key_up:
        flags |= KEYEVENTF_KEYUP
    if vk in _EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = _INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = 0  # MUST be zero when KEYEVENTF_SCANCODE is set
    inp.ki.wScan = scan & 0xFFFF
    inp.ki.dwFlags = flags
    inp.ki.time = 0
    inp.ki.dwExtraInfo = None
    sent = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
    return sent == 1


def _foreground_window_title() -> str:
    """Return the title of whichever window currently has Win32 foreground
    focus, or empty string on any failure (non-Windows / API error). Used
    by ``fire()`` to log which window will actually receive each keypress.

    The single most useful diagnostic when a key step "fires" but the game
    doesn't respond — usually focus is somewhere unexpected (PhantomClick,
    Discord, the desktop) at the moment the key event lands."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""
    except Exception:
        return ""


_MOD_MAP = {
    "ctrl": keyboard.Key.ctrl,
    "control": keyboard.Key.ctrl,
    "shift": keyboard.Key.shift,
    "alt": keyboard.Key.alt,
    "win": keyboard.Key.cmd,
    "cmd": keyboard.Key.cmd,
    "super": keyboard.Key.cmd,
    "meta": keyboard.Key.cmd,
}


# Pynput Key enum → Win32 VK code. Built lazily so missing enum members
# in older pynput versions are tolerated (getattr returns None and the
# entry is skipped). This is the table we consult to resolve modifiers
# and named base keys (space, f5, arrow keys, etc.) to scancode events.
def _build_key_enum_to_vk() -> dict:
    items = [
        ("ctrl", 0x11), ("shift", 0x10), ("alt", 0x12), ("cmd", 0x5B),
        ("space", 0x20), ("enter", 0x0D), ("tab", 0x09),
        ("backspace", 0x08), ("delete", 0x2E), ("esc", 0x1B),
        ("up", 0x26), ("down", 0x28), ("left", 0x25), ("right", 0x27),
        ("home", 0x24), ("end", 0x23),
        ("page_up", 0x21), ("page_down", 0x22),
        ("insert", 0x2D),
        ("f1", 0x70), ("f2", 0x71), ("f3", 0x72), ("f4", 0x73),
        ("f5", 0x74), ("f6", 0x75), ("f7", 0x76), ("f8", 0x77),
        ("f9", 0x78), ("f10", 0x79), ("f11", 0x7A), ("f12", 0x7B),
        ("f13", 0x7C), ("f14", 0x7D), ("f15", 0x7E), ("f16", 0x7F),
        ("caps_lock", 0x14), ("num_lock", 0x90), ("scroll_lock", 0x91),
        ("menu", 0x5D), ("print_screen", 0x2C),
    ]
    out = {}
    for name, vk in items:
        k = getattr(keyboard.Key, name, None)
        if k is not None:
            out[k] = vk
    return out


_KEY_ENUM_TO_VK: dict = _build_key_enum_to_vk()


def _resolve_vk(part) -> Optional[int]:
    """Map a parsed combo element to a Win32 virtual-key code.

    Accepts: a single-char string (uses ``VkKeyScanW``) or a pynput
    ``keyboard.Key`` enum value (uses ``_KEY_ENUM_TO_VK`` lookup, with
    ``part.value.vk`` as a final fallback). Returns ``None`` when the
    part can't be mapped — ``fire()`` rejects the whole combo in that
    case rather than silently sending a partial sequence."""
    if isinstance(part, str):
        if len(part) != 1:
            return None
        if _user32 is None:
            return None
        try:
            res = _user32.VkKeyScanW(part)
        except Exception:
            return None
        # Cast to unsigned 16-bit then check for the documented failure
        # sentinel (VkKeyScanW returns -1 for "no translation").
        rv = int(res)
        if rv == -1 or rv == 0xFFFF:
            return None
        return rv & 0xFF
    vk = _KEY_ENUM_TO_VK.get(part)
    if vk is not None:
        return vk
    try:
        v = getattr(part, "value", None)
        if v is not None and getattr(v, "vk", None) is not None:
            return int(v.vk)
    except Exception:
        pass
    return None

# Special non-character keys we accept as the base key. pynput exposes
# these on keyboard.Key; lookup is by the same lowercase name pynput uses.
_NAMED_KEYS = {
    "space", "enter", "return", "tab", "backspace", "delete",
    "esc", "escape", "up", "down", "left", "right",
    "home", "end", "page_up", "page_down", "pageup", "pagedown",
    "insert", "ins",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9",
    "f10", "f11", "f12", "f13", "f14", "f15", "f16",
    "caps_lock", "num_lock", "scroll_lock",
    "menu", "print_screen",
}

# Aliases the user might type → pynput's canonical name.
_KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
    "pageup": "page_up",
    "pagedown": "page_down",
    "ins": "insert",
    "del": "delete",
    "spacebar": "space",
    "spc": "space",
    " ": "space",
}


VALID_INTERVAL_UNITS = ("ms", "s", "min", "hr")


@dataclass
class KeyTimer:
    """Single passive keypress timer."""
    key: str = "z"                  # combo string, lowercase, ``+``-joined
    interval_min: float = 360.0     # seconds between fires (low end)
    interval_max: float = 360.0     # seconds between fires (high end)
    enabled: bool = True
    # Display unit for the GUI — one of ``"ms" | "s" | "min" | "hr"``.
    # Storage remains in seconds (interval_min/_max). The new single-
    # value UI sets min==max from a value-and-unit pair; jitter-on-top
    # provides the randomness so RS-style detection doesn't see exact
    # cadences.
    interval_unit: str = "min"

    def to_json(self) -> dict:
        return {
            "key": str(self.key or "").lower(),
            "interval_min": float(self.interval_min),
            "interval_max": float(self.interval_max),
            "enabled": bool(self.enabled),
            "interval_unit": (self.interval_unit
                              if self.interval_unit in VALID_INTERVAL_UNITS
                              else "min"),
        }

    @classmethod
    def from_json(cls, d: Optional[dict]) -> Optional["KeyTimer"]:
        if not isinstance(d, dict):
            return None
        try:
            lo = max(0.5, float(d.get("interval_min", 360.0)))
            hi = max(lo, float(d.get("interval_max", lo)))
            unit = str(d.get("interval_unit", "min"))
            if unit not in VALID_INTERVAL_UNITS:
                unit = "min"
            return cls(
                key=str(d.get("key") or "").lower(),
                interval_min=lo,
                interval_max=hi,
                enabled=bool(d.get("enabled", True)),
                interval_unit=unit,
            )
        except (TypeError, ValueError):
            return None


def parse_combo(combo: str) -> Optional[tuple[list, object]]:
    """Parse a ``+``-joined combo string into ``(modifiers, base_key)``.

    Returns ``None`` if the string is empty or the base key isn't
    recognized.  Modifiers are pynput Key enum values; the base is either
    a single character (a-z, 0-9, punctuation) for ``Controller.press`` or
    a pynput Key for named/special keys.

    A literal space character is accepted as the spacebar (``"space"``)
    so users can simply tap the key in the combo entry without having
    to spell it. ``"+"`` is reserved as the modifier separator, so to
    bind the plus key itself, type ``"plus"``.
    """
    if not combo:
        return None
    raw_parts = combo.split("+")
    parts: list[str] = []
    for p in raw_parts:
        # A token that was only whitespace stands in for the spacebar
        # (otherwise ``.strip()`` would drop it and the combo would
        # parse to empty).
        if p and not p.strip():
            parts.append("space")
        elif p.strip():
            parts.append(p.strip().lower())
    if not parts:
        return None
    *mod_parts, base = parts
    mods = []
    for m in mod_parts:
        if m not in _MOD_MAP:
            return None
        mods.append(_MOD_MAP[m])
    base = _KEY_ALIASES.get(base, base)
    if base in _NAMED_KEYS:
        try:
            base_key = getattr(keyboard.Key, base)
        except AttributeError:
            return None
        return (mods, base_key)
    if len(base) == 1:
        return (mods, base)
    # Unknown multi-char token (e.g. "ctrl" with no base, "frobnicate").
    return None


def display(combo: str) -> str:
    """Pretty-print a combo for the GUI: ``"ctrl+z"`` -> ``"Ctrl + Z"``.

    A whitespace-only token is rendered as the spacebar to match the
    parser's behaviour ("ctrl+ " → "Ctrl + Space").
    """
    if not combo:
        return ""
    parts: list[str] = []
    for p in combo.split("+"):
        if p and not p.strip():
            parts.append("space")
        elif p.strip():
            parts.append(p.strip())
    pretty = []
    for p in parts:
        pl = p.lower()
        if pl in _MOD_MAP:
            pretty.append(pl.capitalize() if pl != "win" else "Win")
        elif len(pl) == 1:
            pretty.append(pl.upper())
        elif pl.startswith("f") and pl[1:].isdigit():
            pretty.append(pl.upper())
        else:
            pretty.append(pl.replace("_", " ").title())
    return " + ".join(pretty)


# Default tap-hold range when the caller doesn't pass an explicit
# ``hold_s``. Real human key taps cluster around 70-110 ms; the old
# 30 ms floor was right at the edge of game input sampling and led to
# RS users reporting silently-dropped keypresses. 50-110 ms reliably
# crosses 3+ frames at 60 FPS while still feeling like a tap, and the
# randomization breaks the exact-period signature bot detectors flag.
_TAP_HOLD_MIN_S = 0.050
_TAP_HOLD_MAX_S = 0.110

# Floor for explicit ``hold_s > 0`` callers. Even an "instant" charge
# input needs enough time for the OS to dispatch the press event before
# the release lands.
_MIN_KEY_HOLD_S = 0.045

# Frame-gap between modifier press and base press (and base release and
# modifier release) for combos like ctrl+x. Without it, SendInput can
# burst both events into the same poll cycle and the game sees the base
# key arrive before it has registered the modifier — combo lost.
_MOD_GAP_MIN_S = 0.008
_MOD_GAP_MAX_S = 0.018


def _hold_sleep(stop: Optional[threading.Event], seconds: float) -> None:
    """Interruptible sleep that always returns (so the press/release pair
    completes cleanly even when ``stop`` fires mid-hold)."""
    if seconds <= 0:
        return
    if stop is not None:
        stop.wait(seconds)
    else:
        time.sleep(seconds)


def fire(
    controller: keyboard.Controller,
    combo: str,
    hold_s: float = 0.0,
    stop: Optional[threading.Event] = None,
) -> bool:
    """Press a parsed combo once.

    When ``hold_s == 0`` (default tap), the hold duration is randomized in
    ``[50, 110] ms`` — humanlike and well above any modern game's input
    poll window. When ``hold_s > 0`` (charge/release inputs) the explicit
    duration is used, floored at ``_MIN_KEY_HOLD_S``. For combos with
    modifiers, a small randomized frame-gap separates modifier-press from
    base-press (and base-release from modifier-release) so games don't
    drop the modifier when both arrive in the same input poll. The hold
    is interruptible via ``stop`` so the engine's stop signal still aborts
    cleanly mid-hold; the key (and any modifiers) are always released on
    the way out.

    Returns True on success, False on a parse error or pynput exception.
    """
    parsed = parse_combo(combo)
    if parsed is None:
        _log.warning("key fire combo=%r REJECTED (parse_combo returned None)", combo)
        return False
    mods, base = parsed

    # Resolve everything to Win32 VK codes upfront. If any element fails
    # to resolve, bail entirely — we never want to send half a combo.
    base_vk = _resolve_vk(base)
    if base_vk is None:
        _log.warning(
            "key fire combo=%r REJECTED (couldn't resolve VK for base %r)",
            combo, base,
        )
        return False
    mod_vks: list[int] = []
    for m in mods:
        mvk = _resolve_vk(m)
        if mvk is None:
            _log.warning(
                "key fire combo=%r REJECTED (couldn't resolve VK for modifier %r)",
                combo, m,
            )
            return False
        mod_vks.append(mvk)

    if hold_s <= 0.0:
        actual_hold = random.uniform(_TAP_HOLD_MIN_S, _TAP_HOLD_MAX_S)
    else:
        actual_hold = max(_MIN_KEY_HOLD_S, float(hold_s))
    # Capture focus state BEFORE we touch anything so the log shows
    # which window will receive the upcoming press. perf_counter gives
    # us sub-ms precision for the actual hold duration.
    target_window = _foreground_window_title()
    mod_names = [str(m).split(".")[-1].rstrip("'>") for m in mods]
    base_name = str(base) if not isinstance(base, str) else f"'{base}'"
    t_press = 0.0
    t_release = 0.0
    # NOTE: ``controller`` is accepted for back-compat with the old
    # pynput-based signature but is not used — we now go through
    # ``_send_scancode`` directly so the keystrokes look like hardware
    # events (KEYEVENTF_SCANCODE), which is what Java AWT / DirectInput
    # / RawInput games actually listen for.
    # Pick the active backend once per fire so a config change between
    # sends doesn't split a press from its release across two backends.
    backend = _active_backend()

    # Track per-event acceptance. SendInput can reject silently (returns
    # 0 sent) under UIPI / session-isolation / desktop-switch conditions;
    # Interception can reject when the driver isn't bound to a device.
    # Without per-event accounting "ok=True" hid those failures.
    sends_ok = 0
    sends_total = 0
    last_err = 0
    try:
        for mvk in mod_vks:
            sends_total += 1
            if backend.send(mvk, key_up=False):
                sends_ok += 1
            else:
                last_err = _last_sendinput_error()
        if mod_vks:
            _hold_sleep(stop, random.uniform(_MOD_GAP_MIN_S, _MOD_GAP_MAX_S))
        try:
            t_press = time.perf_counter()
            sends_total += 1
            if backend.send(base_vk, key_up=False):
                sends_ok += 1
            else:
                last_err = _last_sendinput_error()
            _hold_sleep(stop, actual_hold)
            t_release = time.perf_counter()
            sends_total += 1
            if backend.send(base_vk, key_up=True):
                sends_ok += 1
            else:
                last_err = _last_sendinput_error()
            if mod_vks:
                _hold_sleep(stop, random.uniform(_MOD_GAP_MIN_S, _MOD_GAP_MAX_S))
        finally:
            for mvk in reversed(mod_vks):
                try:
                    sends_total += 1
                    if backend.send(mvk, key_up=True):
                        sends_ok += 1
                    else:
                        last_err = _last_sendinput_error()
                except Exception:
                    pass
        actual_hold_ms = (t_release - t_press) * 1000.0
        _log.info(
            "key fire combo=%r base=%s mods=%s hold_req=%.0fms hold_act=%.1fms "
            "target_window=%r sends=%d/%d last_err=%d ok=%s backend=%s",
            combo, base_name, mod_names,
            actual_hold * 1000.0, actual_hold_ms, target_window,
            sends_ok, sends_total, last_err, sends_ok == sends_total,
            getattr(backend, "name", "?"),
        )
        return sends_ok == sends_total
    except Exception as e:
        _log.warning(
            "key fire combo=%r base=%s mods=%s target_window=%r FAILED: %s: %s",
            combo, base_name, mod_names, target_window,
            type(e).__name__, e,
        )
        # Best-effort modifier release on any failure path.
        for mvk in reversed(mod_vks):
            try:
                _send_scancode(mvk, key_up=True)
            except Exception:
                pass
        return False


def run_timer_loop(
    timer: KeyTimer,
    stop: threading.Event,
    controller: Optional[keyboard.Controller] = None,
    jitter_enabled: bool = True,
    jitter_pct: float = 0.10,
) -> None:
    """Drive a single timer until ``stop`` is set.

    Uses ``stop.wait(secs)`` for the inter-fire delay so Stop is instant.
    Each interval is sampled fresh from ``[interval_min, interval_max]``,
    then optionally multiplied by a uniform ``[1 - p, 1 + p]`` jitter so
    that a user who sets both bounds to the same value (e.g. "exactly
    15 min") still gets natural variation. RuneScape's bot detector
    flags exact-periodic cadences; the default ±10% jitter breaks that
    pattern without changing the user's intended timing range.
    """
    if controller is None:
        controller = keyboard.Controller()
    if not timer.enabled or not timer.key:
        return
    if parse_combo(timer.key) is None:
        return
    p = max(0.0, min(0.5, float(jitter_pct))) if jitter_enabled else 0.0
    while not stop.is_set():
        lo = max(0.5, float(timer.interval_min))
        hi = max(lo, float(timer.interval_max))
        wait_s = random.uniform(lo, hi)
        if p > 0.0:
            wait_s *= random.uniform(1.0 - p, 1.0 + p)
            wait_s = max(0.5, wait_s)
        if stop.wait(wait_s):
            return
        fire(controller, timer.key)


def serialize_timers(timers: list[KeyTimer]) -> list[dict]:
    return [t.to_json() for t in timers]


def deserialize_timers(raw: object) -> list[KeyTimer]:
    if not isinstance(raw, list):
        return []
    out: list[KeyTimer] = []
    for item in raw:
        t = KeyTimer.from_json(item)
        if t is not None:
            out.append(t)
    return out
