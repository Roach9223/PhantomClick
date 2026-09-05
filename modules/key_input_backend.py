"""Pluggable keyboard-event backends.

Why this exists: ``modules.key_timer.fire()`` used to call SendInput
directly (via the scancode helpers in ``key_timer``). For most apps that
works perfectly, but some games, most notably RuneScape NXT, use
kernel-level filters that drop **every** event the kernel marks as
``LLMHF_INJECTED``. SendInput-injected events always carry that flag, so
the macro fires (and the log says ``ok=True``), but the game ignores
them.

To beat that filter, we route key events through a virtual hardware
driver (Interception) when the user opts in. Events emitted via that
path arrive at the input stack without the injected flag.

This module presents a tiny ``KeyBackend`` interface plus two concrete
backends:

* ``SendInputBackend``, the default. Uses the existing ctypes SendInput
  scancode path in ``key_timer``. Fast, zero deps, works in 95% of apps.
* ``InterceptionBackend``, opt-in. Wraps the ``interception`` Python
  binding for the Interception driver. Requires a one-time admin install
  of the driver itself; the Python wrapper is an optional dep so missing
  it doesn't break startup.

``get_backend(preferred)`` picks one. ``preferred ∈ {"auto",
"sendinput", "interception"}``. The ``"auto"`` mode prefers Interception
when it's actually usable and silently falls back to SendInput
otherwise.
"""

from __future__ import annotations

import threading
import time
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
# SendInput backend (default, wraps the existing scancode path)
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
# Interception backend (opt-in, bypasses NXT's injected-event filter)
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
    driver / wrapper isn't available, ``available`` reports the truth
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
        # we still try to send, some forks auto-bind on first call.
        try:
            if hasattr(_ictrl, "auto_capture_devices"):
                _ictrl.auto_capture_devices()
        except Exception as e:
            # Could mean the driver isn't installed, most common cause
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
# Serial HID backend (opt-in, real USB HID via Arduino bridge)
# ---------------------------------------------------------------------- #

class SerialHidBackend:
    """Routes keyboard events through an Arduino flashed as USB HID.

    Why: NXT (and similar BotWatch-style filters) reject SendInput,
    Interception, AND PostMessage by correlating each event against a
    Raw Input WM_INPUT from a registered real-HID device handle. No
    software-only path satisfies that check. A second physical USB
    keyboard does, trivially. The Arduino IS that second keyboard , 
    it enumerates as a real USB HID device, so its keystrokes carry
    a real RAWINPUTHEADER.hDevice and pass every filter.

    Protocol matches ``firmware/phantomhid/phantomhid.ino``:
        ``D <vk>\\n``  press down a Win32 VK
        ``U <vk>\\n``  release a Win32 VK
        ``P\\n``       ping (replies ``OK PHANTOMHID v1\\n``)
        ``X\\n``       release every held key (replies ``OK RELEASED\\n``)

    Instances own the COM port. Get one through ``get_backend`` (cached
    per port) rather than constructing directly, and ``close()`` it when
    it is replaced; a second open of the same port fails on Windows.
    """

    name = "serial_hid"

    # How long to wait for the firmware to answer the startup ping. The
    # 32u4 CDC stack answers within a few ms once enumerated; the budget
    # is generous so a busy USB hub doesn't produce a false warning.
    _PING_TIMEOUT_S = 0.6

    def __init__(self, port: str = "", baud: int = 115200) -> None:
        self.available = False
        self.firmware_ok = False
        self._port = port
        self._baud = int(baud) if baud else 115200
        self._serial = None
        self._init_error = ""

        if not port:
            self._init_error = (
                "no COM port configured for Serial HID, pick one in "
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
        self._ping()

    def _ping(self) -> None:
        """Send ``P`` once and check the reply names PhantomHID. A wrong
        board (or a board running some other sketch) opens fine and
        swallows every ``D``/``U`` line, so this is the only early
        signal that the user picked the right COM port."""
        reply = b""
        try:
            self._serial.reset_input_buffer()
            self._serial.write(b"P\n")
            deadline = time.monotonic() + self._PING_TIMEOUT_S
            while time.monotonic() < deadline:
                line = self._serial.readline()
                if line:
                    reply = line.strip()
                    break
        except Exception as e:
            _log.warning("serial_hid %s: ping failed: %s: %s",
                         self._port, type(e).__name__, e)
            return
        if b"PHANTOMHID" in reply.upper():
            self.firmware_ok = True
            _log.info("serial_hid %s: firmware answered %r",
                      self._port, reply.decode("ascii", "replace"))
        else:
            _log.warning(
                "serial_hid %s: ping reply %r does not look like PhantomHID "
                "(expected 'OK PHANTOMHID v1'); keystrokes may be ignored. "
                "Check the COM port and that the board runs "
                "firmware/phantomhid/phantomhid.ino.",
                self._port, reply.decode("ascii", "replace"),
            )

    def is_open(self) -> bool:
        s = self._serial
        return bool(self.available and s is not None
                    and getattr(s, "is_open", True))

    def release_all(self) -> bool:
        """Send the firmware's release-all. Used at engine stop so a
        modifier from an interrupted combo can't stay held on the board
        (the OS would otherwise see Ctrl down until the next press)."""
        s = self._serial
        if s is None:
            return False
        try:
            s.write(b"X\n")
            return True
        except Exception as e:
            _log.warning("serial_hid %s: release-all failed: %s: %s",
                         self._port, type(e).__name__, e)
            return False

    def close(self) -> None:
        """Release the COM port. Idempotent."""
        s = self._serial
        self._serial = None
        self.available = False
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

    def send(self, vk: int, key_up: bool) -> bool:
        """Write one ``D``/``U`` line. Returns True on a clean write.

        On any serial error we mark the backend unavailable so the
        caller knows to fall back / surface the error. Reconnect logic
        is handled by re-running ``get_backend()`` at engine restart , 
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

# Cache the Interception backend across get_backend() calls, its
# constructor probes the driver, which is non-trivial work; rebuilding
# per cycle would slow engine startup needlessly.
_interception_singleton: Optional[InterceptionBackend] = None


def _get_interception() -> InterceptionBackend:
    global _interception_singleton
    if _interception_singleton is None:
        _interception_singleton = InterceptionBackend()
    return _interception_singleton


# Serial HID backends cached by COM port. Constructing one opens the
# port, and Windows refuses a second open of the same port, so every
# caller (engine start, per-step Test, the UI's pre-start status check)
# must share the one instance. Failed opens are not cached so a board
# plugged in later gets a fresh attempt.
_serial_backends: dict[str, SerialHidBackend] = {}
_serial_lock = threading.Lock()


def _acquire_serial(port: str) -> SerialHidBackend:
    key = (port or "").strip().upper()
    with _serial_lock:
        existing = _serial_backends.get(key)
        if existing is not None and existing.is_open():
            return existing
        # Anything still cached is either dead or for a port the user
        # has moved away from; free it before opening.
        for k, b in list(_serial_backends.items()):
            b.close()
            _serial_backends.pop(k, None)
        fresh = SerialHidBackend(port=port)
        if fresh.available:
            _serial_backends[key] = fresh
        return fresh


def release_all(backend) -> bool:
    """Ask ``backend`` to release every held key, if it can. Only the
    Serial HID path has device-side state to clear; other backends
    return False and that is fine."""
    fn = getattr(backend, "release_all", None)
    if not callable(fn):
        return False
    try:
        return bool(fn())
    except Exception:
        return False


def status(backend) -> tuple[bool, str]:
    """``(available, human message)`` for a backend, so the UI can show
    the state (and refuse start) before the engine runs."""
    name = getattr(backend, "name", "?")
    if not getattr(backend, "available", True):
        err = getattr(backend, "_init_error", "") or f"{name} backend unavailable"
        return (False, err)
    if name == "serial_hid":
        port = getattr(backend, "_port", "") or "?"
        if getattr(backend, "firmware_ok", False):
            return (True, f"Serial HID ready on {port} (PhantomHID answered)")
        return (True, f"Serial HID open on {port}, but the board did not "
                      f"answer the PhantomHID ping. Keystrokes may be ignored.")
    if name == "interception":
        return (True, "Interception driver ready")
    return (True, "SendInput ready")


def get_backend(preferred: str, *, serial_port: str = "") -> KeyBackend:
    """Return the backend to use this session.

    ``preferred``:
      * ``"auto"`` (default), Interception when actually usable, else
        SendInput. Logs which one was chosen at info level. ``auto``
        does NOT pick ``serial_hid`` because that backend depends on
        physical hardware that may not be connected; users who want it
        have to pick it explicitly.
      * ``"sendinput"``, force SendInput. Useful for non-RS targets
        where the extra driver path is overkill.
      * ``"interception"``, force Interception. If the driver isn't
        available, this still returns the Interception backend (with
        ``available=False``); the caller is responsible for surfacing
        the error to the user, we don't silently fall back when the
        user explicitly picked it.
      * ``"serial_hid"``, force Serial HID via the Arduino bridge
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
        return _acquire_serial(serial_port)
    # auto: prefer Interception if we can, else SendInput.
    ictr = _get_interception()
    if ictr.available:
        return ictr
    if ictr._init_error:
        _log.info("key_input_method=auto: %s, falling back to SendInput",
                  ictr._init_error)
    return SendInputBackend()
