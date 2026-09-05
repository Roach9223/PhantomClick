"""Low-level-hook diagnostic for Interception delivery.

A WH_KEYBOARD_LL hook sees every keyboard event the OS dispatches —
real or injected, regardless of which window has focus. We use it to
ground-truth whether the Interception driver is actually emitting
events into the kernel input stack.

For each Interception slot 0..9 with a populated HWID, we fire a single
spacebar press+release and count how many WM_KEYDOWN+WM_KEYUP pairs
the LL hook observes for VK_SPACE. The hook also reports whether the
LLKHF_INJECTED flag was set — Interception-injected events should NOT
have it (that's the whole point); SendInput events always do.

No focus juggling needed: just run the script, don't touch the
keyboard while it's counting.

Output legend per slot:
  fired=N seen=N injected=0  -> driver is delivering, not flagged as injected (success)
  fired=N seen=N injected=N  -> events reach the OS but flagged as injected (wrong path)
  fired=N seen=0             -> driver call returned ok but nothing reached the OS
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import threading
import time

sys.path.insert(0, r"F:\.programs\AutoClicker")

import interception  # type: ignore
from interception import _keycodes  # type: ignore
from interception.constants import KeyFlag  # type: ignore
from interception.inputs import _g_context  # type: ignore
from interception.strokes import KeyStroke  # type: ignore


WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
LLKHF_INJECTED = 0x10
VK_SPACE = 0x20


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wt.LPARAM, ctypes.c_int, wt.WPARAM, wt.LPARAM
)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, wt.HMODULE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = wt.LPARAM
user32.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]


# Stats accumulated by the hook callback
seen_total = 0
seen_space = 0
seen_injected = 0
hook_thread_id = 0
_hook_stop_msg = 0x0401  # WM_USER + 1


def _hook_proc(nCode, wParam, lParam):
    global seen_total, seen_space, seen_injected
    if nCode == 0:
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        seen_total += 1
        if kb.vkCode == VK_SPACE and wParam in (WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP):
            seen_space += 1
            if kb.flags & LLKHF_INJECTED:
                seen_injected += 1
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


_HOOK_PROC = LowLevelKeyboardProc(_hook_proc)


def _hook_pump_thread(ready: threading.Event, stop: threading.Event):
    global hook_thread_id
    hook_thread_id = kernel32.GetCurrentThreadId()
    h = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _HOOK_PROC, None, 0)
    if not h:
        print(f"!! SetWindowsHookExW failed: GetLastError={ctypes.get_last_error()}")
        ready.set()
        return
    ready.set()
    msg = ctypes.create_string_buffer(48)
    while not stop.is_set():
        rv = user32.PeekMessageW(msg, None, 0, 0, 1)  # PM_REMOVE
        if rv:
            # Drain any thread messages so PostThreadMessage wakes us up.
            pass
        time.sleep(0.005)
    user32.UnhookWindowsHookEx(h)


user32.PeekMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT, wt.UINT]
user32.PeekMessageW.restype = wt.BOOL


def fire_via_slot(slot: int) -> None:
    data = _keycodes.get_key_information("space")
    down = KeyStroke(data.scan_code, KeyFlag.KEY_DOWN)
    up = KeyStroke(data.scan_code, KeyFlag.KEY_UP)
    _g_context.send(slot, down)
    time.sleep(0.06)
    _g_context.send(slot, up)


def main() -> None:
    global seen_total, seen_space, seen_injected

    interception.auto_capture_devices(verbose=False)

    populated = []
    for s in range(10):
        try:
            hwid = _g_context.devices[s].get_HWID()
        except Exception:
            hwid = None
        if hwid:
            populated.append((s, hwid[:60]))

    if not populated:
        print("No populated keyboard slots — driver may not be loaded.")
        return

    print("Populated keyboard slots:")
    for s, h in populated:
        print(f"  slot {s}: {h}")
    print(f"auto-bound active keyboard slot: {_g_context.keyboard}")
    print()

    ready = threading.Event()
    stop = threading.Event()
    t = threading.Thread(target=_hook_pump_thread, args=(ready, stop), daemon=True)
    t.start()
    ready.wait(2.0)
    time.sleep(0.2)  # give the hook a moment to attach

    print("Hook attached. Don't press any keys for the next ~5 seconds.")
    time.sleep(0.5)

    # Per-slot driver send
    for s, _ in populated:
        seen_space = 0
        seen_injected = 0
        seen_total = 0
        try:
            fire_via_slot(s)
            time.sleep(0.20)  # let hook drain
            verdict = ""
            if seen_space == 0:
                verdict = "DRIVER NOT DELIVERING"
            elif seen_injected == 0:
                verdict = "DELIVERED, hardware-flagged (good for NXT)"
            else:
                verdict = "DELIVERED but LLMHF_INJECTED set (NXT will block)"
            print(f"  slot={s}: fired=2 space_seen={seen_space} "
                  f"injected={seen_injected} total_kbd={seen_total} -> {verdict}")
        except Exception as e:
            print(f"  slot={s}: FAILED {type(e).__name__}: {e}")

    # SendInput control test (should be flagged injected)
    seen_space = 0
    seen_injected = 0
    seen_total = 0
    from modules import key_input_backend  # type: ignore
    s = key_input_backend.get_backend("sendinput")
    s.send(VK_SPACE, key_up=False)
    time.sleep(0.06)
    s.send(VK_SPACE, key_up=True)
    time.sleep(0.20)
    print(f"  SendInput control: space_seen={seen_space} injected={seen_injected} "
          f"(expect injected==space_seen — SendInput always flags injected)")

    stop.set()
    t.join(timeout=2.0)


if __name__ == "__main__":
    main()
