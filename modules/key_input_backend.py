"""Pluggable keyboard-event backends.

Why this exists: ``modules.key_timer.fire()`` used to call SendInput
directly (via the scancode helpers in ``key_timer``). For most apps that
works perfectly, but some games — most notably RuneScape NXT — use
kernel-level filters that drop **every** event the kernel marks as
``LLMHF_INJECTED``. SendInput-injected events always carry that flag, so
the macro fires (and the log says ``ok=True``), but the game ignores
them.

To beat that filter, we route key events through a virtual hardware
driver (Interception) when the user opts in. Events emitted via that
path arrive at the input stack without the injected flag.

This module presents a tiny ``KeyBackend`` interface plus two concrete
backends:

* ``SendInputBackend`` — the default. Uses the existing ctypes SendInput
  scancode path in ``key_timer``. Fast, zero deps, works in 95% of apps.
* ``InterceptionBackend`` — opt-in. Wraps the ``interception`` Python
  binding for the Interception driver. Requires a one-time admin install
  of the driver itself; the Python wrapper is an optional dep so missing
  it doesn't break startup.

``get_backend(preferred)`` picks one. ``preferred ∈ {"auto",
"sendinput", "interception"}``. The ``"auto"`` mode prefers Interception
when it's actually usable and silently falls back to SendInput
otherwise.
"""

from __future__ import annotations

from typing import Optional, Protocol

from utils.logger import get_logger

_log = get_logger()


class KeyBackend(Protocol):
    """Minimal contract: emit one keyboard event (press or release) for a
    given Win32 virtual-key code. Returns True on success, False on any
    rejection. ``name`` and ``available`` let callers describe which
    path was actually selected and gate fallbacks."""

    name: str
    available: bool

    def send(self, vk: int, key_up: bool) -> bool: ...


# ---------------------------------------------------------------------- #
# SendInput backend (default — wraps the existing scancode path)
# ---------------------------------------------------------------------- #

class SendInputBackend:
    """Defers to ``key_timer._send_scancode``. The scancode logic lives
    in ``key_timer`` because that's where the ctypes structures and
    extended-key set were already defined; this backend is a thin
    selectable shim around it."""

    name = "sendinput"
    available = True

    def send(self, vk: int, key_up: bool) -> bool:
        # Lazy import to keep the dependency direction clean: key_timer
        # imports this module to grab the active backend, so importing
        # key_timer at module load would create a cycle.
        from . import key_timer
        return key_timer._send_scancode(vk, key_up)


# ---------------------------------------------------------------------- #
# Interception backend (opt-in — bypasses NXT's injected-event filter)
# ---------------------------------------------------------------------- #

# VK → string name accepted by the ``interception`` library's high-level
# API. The library maps these names to scancodes internally; we keep our
# own VK pipeline upstream for parsing-time consistency, then translate
# at the last moment when we're committed to using Interception.
#
# Coverage: everything our parser actually produces. ASCII letters/digits
# are handled programmatically. Anything outside this set falls back to
# SendInput (returning False from send()).
_VK_TO_INTERCEPTION_NAME: dict[int, str] = {
    # Modifiers
    0x10: "shift",
    0x11: "ctrl",
    0x12: "alt",
    0x5B: "lwin",
    # Whitespace / control
    0x20: "space",
    0x0D: "enter",
    0x09: "tab",
    0x08: "backspace",
    0x1B: "esc",
    # Editing pad
    0x2D: "insert",
    0x2E: "delete",
    0x24: "home",
    0x23: "end",
    0x21: "page_up",
    0x22: "page_down",
    # Arrows
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    # Locks / system
    0x14: "caps_lock",
    0x90: "num_lock",
    0x91: "scroll_lock",
    0x2C: "print_screen",
    # Function keys
    0x70: "f1", 0x71: "f2", 0x72: "f3", 0x73: "f4",
    0x74: "f5", 0x75: "f6", 0x76: "f7", 0x77: "f8",
    0x78: "f9", 0x79: "f10", 0x7A: "f11", 0x7B: "f12",
}


def _vk_to_interception_name(vk: int) -> Optional[str]:
    """Map a Win32 VK to the string name the Interception wrapper
    expects. Returns None for VKs we don't recognize."""
    if vk in _VK_TO_INTERCEPTION_NAME:
        return _VK_TO_INTERCEPTION_NAME[vk]
    # ASCII letters: VK_A..VK_Z = 0x41..0x5A → 'a'..'z'
    if 0x41 <= vk <= 0x5A:
        return chr(vk + 0x20)
    # ASCII digits: VK_0..VK_9 = 0x30..0x39 → '0'..'9'
    if 0x30 <= vk <= 0x39:
        return chr(vk)
    return None


class InterceptionBackend:
    """Routes keyboard events through the Interception driver via the
    ``interception`` Python wrapper. Construction succeeds even when the
    driver / wrapper isn't available — ``available`` reports the truth
    so callers can decide between erroring or falling back."""

    name = "interception"

    def __init__(self) -> None:
        self.available = False
        self._mod = None
        self._init_error = ""
        try:
            import interception as _ictrl  # type: ignore[import-not-found]
        except Exception as e:
            self._init_error = (
                f"interception python wrapper not importable ({type(e).__name__}: {e}). "
                f"Run `pip install interception-python` after installing the driver."
            )
            return
        self._mod = _ictrl
        # Different forks of the wrapper have slightly different init
        # entry points. ``auto_capture_devices`` is the most common name
        # in the maintained kennyhml fork. Best-effort: if it's missing
        # we still try to send — some forks auto-bind on first call.
        try:
            if hasattr(_ictrl, "auto_capture_devices"):
                _ictrl.auto_capture_devices()
        except Exception as e:
            # Could mean the driver isn't installed — most common cause
            # is the user pip-installed the wrapper but skipped the
            # admin driver install. Surface that distinct case in the
            # init message so the UI can show the right tooltip.
            self._init_error = (
                f"interception driver not detected ({type(e).__name__}: {e}). "
                f"Install from https://github.com/oblitum/Interception "
                f"with admin privileges, then reboot."
            )
            return
        self.available = True

    def send(self, vk: int, key_up: bool) -> bool:
        if not self.available or self._mod is None:
            return False
        name = _vk_to_interception_name(vk)
        if name is None:
            # We don't have a Interception name for this VK; refuse so
            # the caller can fall back to SendInput rather than silently
            # dropping the event.
            return False
        try:
            if key_up:
                self._mod.key_up(name)
            else:
                self._mod.key_down(name)
            return True
        except Exception as e:
            _log.warning("interception send failed vk=0x%02X name=%r: %s: %s",
                         vk, name, type(e).__name__, e)
            return False


# ---------------------------------------------------------------------- #
# Serial HID backend (opt-in — real USB HID via Arduino bridge)
# ---------------------------------------------------------------------- #

class SerialHidBackend:
    """Routes keyboard events through an Arduino flashed as USB HID.

    Why: NXT (and similar BotWatch-style filters) reject SendInput,
    Interception, AND PostMessage by correlating each event against a
    Raw Input WM_INPUT from a registered real-HID device handle. No
    software-only path satisfies that check. A second physical USB
    keyboard does, trivially. The Arduino IS that second keyboard —
    it enumerates as a real USB HID device, so its keystrokes carry
    a real RAWINPUTHEADER.hDevice and pass every filter.

    Protocol matches ``firmware/phantomhid/phantomhid.ino``:
        ``D <vk>\\n``  press down a Win32 VK
        ``U <vk>\\n``  release a Win32 VK
        ``P\\n``       ping (replies ``OK PHANTOMHID v1\\n``)
    """

    name = "serial_hid"

    def __init__(self, port: str = "", baud: int = 115200) -> None:
        self.available = False
        self._port = port
        self._baud = int(baud) if baud else 115200
        self._serial = None
        self._init_error = ""

        if not port:
            self._init_error = (
                "no COM port configured for Serial HID — pick one in "
                "Behavior → Key input method, or run "
                "`python -c \"import serial.tools.list_ports as p; "
                "[print(x.device, x.description) for x in p.comports()]\"` "
                "to see what's plugged in."
            )
            return
        try:
            import serial as _serial  # type: ignore[import-not-found]
        except Exception as e:
            self._init_error = (
                f"pyserial not installed ({type(e).__name__}: {e}). "
                f"Run `pip install pyserial`."
            )
            return
        try:
            # Short read timeout so any future response read doesn't
            # stall the engine. Write timeout protects against a
            # disconnected board hanging the click loop.
            self._serial = _serial.Serial(
                port, self._baud, timeout=0.1, write_timeout=0.5,
            )
        except Exception as e:
            self._init_error = (
                f"could not open {port} at {self._baud} baud "
                f"({type(e).__name__}: {e}). Check the port matches "
                f"the one Arduino IDE used, and that no serial monitor "
                f"is holding it open."
            )
            return
        self.available = True

    def send(self, vk: int, key_up: bool) -> bool:
        """Write one ``D``/``U`` line. Returns True on a clean write.

        On any serial error we mark the backend unavailable so the
        caller knows to fall back / surface the error. Reconnect logic
        is handled by re-running ``get_backend()`` at engine restart —
        we don't try to recover mid-session because the symptom is
        usually "Arduino unplugged" and a silent reconnect would mask
        the user's actual problem."""
        if not self.available or self._serial is None:
            return False
        try:
            cmd = b"U " if key_up else b"D "
            line = cmd + str(int(vk)).encode("ascii") + b"\n"
            self._serial.write(line)
            return True
        except Exception as e:
            _log.warning(
                "serial_hid send failed vk=0x%02X key_up=%s on %s: %s: %s",
                vk, key_up, self._port, type(e).__name__, e,
            )
            self.available = False
            return False


# ---------------------------------------------------------------------- #
# Factory
# ---------------------------------------------------------------------- #

# Cache the Interception backend across get_backend() calls — its
# constructor probes the driver, which is non-trivial work; rebuilding
# per cycle would slow engine startup needlessly.
_interception_singleton: Optional[InterceptionBackend] = None


def _get_interception() -> InterceptionBackend:
    global _interception_singleton
    if _interception_singleton is None:
        _interception_singleton = InterceptionBackend()
    return _interception_singleton


def get_backend(preferred: str, *, serial_port: str = "") -> KeyBackend:
    """Return the backend to use this session.

    ``preferred``:
      * ``"auto"`` (default) — Interception when actually usable, else
        SendInput. Logs which one was chosen at info level. ``auto``
        does NOT pick ``serial_hid`` because that backend depends on
        physical hardware that may not be connected; users who want it
        have to pick it explicitly.
      * ``"sendinput"`` — force SendInput. Useful for non-RS targets
        where the extra driver path is overkill.
      * ``"interception"`` — force Interception. If the driver isn't
        available, this still returns the Interception backend (with
        ``available=False``); the caller is responsible for surfacing
        the error to the user — we don't silently fall back when the
        user explicitly picked it.
      * ``"serial_hid"`` — force Serial HID via the Arduino bridge
        (``firmware/phantomhid``). Requires ``serial_port`` keyword
        argument naming the COM port the board enumerated as. Same
        no-fallback policy as Interception when explicitly chosen.

    ``serial_port`` is only used when ``preferred == "serial_hid"``.
    """
    pref = (preferred or "auto").strip().lower()
    if pref == "sendinput":
        return SendInputBackend()
    if pref == "interception":
        return _get_interception()
    if pref == "serial_hid":
        return SerialHidBackend(port=serial_port)
    # auto: prefer Interception if we can, else SendInput.
    ictr = _get_interception()
    if ictr.available:
        return ictr
    if ictr._init_error:
        _log.info("key_input_method=auto: %s — falling back to SendInput",
                  ictr._init_error)
    return SendInputBackend()
