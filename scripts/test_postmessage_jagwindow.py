"""Test PostMessage delivery to the JagWindow HWND.

Why: Interception delivers events to the OS without LLMHF_INJECTED, but
NXT still ignores them — strongly suggesting NXT filters by Raw Input
device handle (which Interception can't fake; it injects via the
kbdclass aggregate, not a specific HID device handle).

PostMessage bypasses Raw Input entirely and goes straight to the
target window's standard message pump. NXT (Jagex's official client)
runs on Java/LWJGL3/GLFW; on Windows GLFW uses standard WM_KEYDOWN/UP
for keyboard input, NOT Raw Input. So if we PostMessage WM_KEYDOWN to
JagWindow, GLFW should dispatch it to the game's key handler.

If this works, we add a "post_message" backend to PhantomClick alongside
Interception. If NXT *still* ignores it, we know the filter is Java-side
in BotWatch and we need a different approach (real hardware via G HUB
firmware macros, or vJoy).

Test plan:
  1. Have RuneScape NXT running, with spacebar bound to a quick-action.
  2. Run this script. It will find the JagWindow HWND and fire 3
     spacebar PostMessages to it (1-second gaps).
  3. Watch RS — if quick-action fires on each, PostMessage works.
  4. If nothing happens, NXT's filter is above the message pump.

You don't need to focus the script's terminal window — PostMessage
delivers directly to the target HWND regardless of focus.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
VK_SPACE = 0x20

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.PostMessageW.argtypes = [wt.HWND, ctypes.c_uint, wt.WPARAM, wt.LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]


EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _scancode_for_space() -> int:
    """MapVirtualKey VK→scancode for VK_SPACE so the LPARAM is well-formed.
    Some windows / GLFW translate scancode in LPARAM, not just VK in WPARAM."""
    user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
    user32.MapVirtualKeyW.restype = wt.UINT
    return int(user32.MapVirtualKeyW(VK_SPACE, 0))


def find_jagwindow() -> int:
    """Locate the RS NXT window. Class name is 'JagWindow' in the official client."""
    hwnd = user32.FindWindowW("JagWindow", None)
    if hwnd:
        return int(hwnd)
    # Fallback: enumerate all top-level windows looking for one whose
    # title contains 'RuneScape' or class is JagWindow*.
    found = [0]

    def cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        title_len = user32.GetWindowTextLengthW(hwnd)
        if title_len > 0:
            buf = ctypes.create_unicode_buffer(title_len + 1)
            user32.GetWindowTextW(hwnd, buf, title_len + 1)
            title = buf.value
        else:
            title = ""
        if "JagWindow" in cls.value or "RuneScape" in title:
            print(f"  candidate: hwnd=0x{hwnd:08X} class={cls.value!r} title={title!r}")
            found[0] = hwnd
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return int(found[0])


def post_key(hwnd: int, vk: int, scan: int, key_up: bool) -> bool:
    """PostMessage WM_KEYDOWN/UP to a window. LPARAM encodes scancode + flags
    per https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-keydown."""
    msg = WM_KEYUP if key_up else WM_KEYDOWN
    # LPARAM bit layout for keyboard messages:
    #   bits 0..15  = repeat count (1)
    #   bits 16..23 = scancode
    #   bit 24      = extended key
    #   bit 29      = context code (0 for non-Alt)
    #   bit 30      = previous state (1 if KEYUP, 0 if KEYDOWN)
    #   bit 31      = transition state (0 KEYDOWN, 1 KEYUP)
    lparam = 1 | ((scan & 0xFF) << 16)
    if key_up:
        lparam |= (1 << 30) | (1 << 31)
    return bool(user32.PostMessageW(hwnd, msg, vk, lparam))


def main() -> None:
    hwnd = find_jagwindow()
    if not hwnd:
        print("Could not find JagWindow / RuneScape window. Is NXT running?")
        return

    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    title_len = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, title_len + 1))
    user32.GetWindowTextW(hwnd, buf, title_len + 1)
    print(f"target hwnd=0x{hwnd:08X} class={cls.value!r} title={buf.value!r}")

    scan = _scancode_for_space()
    print(f"VK_SPACE scancode={scan} (expect 57)")

    print("\n>>> ALT-TAB TO NXT NOW. Stare at the spacebar quick-action.")
    print("    First pulse fires in 6 seconds. Three total, 2 seconds apart.")
    for n in range(6, 0, -1):
        print(f"    {n}...", flush=True)
        time.sleep(1)

    # Three pulses, 2 seconds apart, so you can see if any of them fire.
    for i in range(3):
        print(f"\n[{i+1}/3] PostMessage WM_KEYDOWN VK_SPACE", flush=True)
        ok_d = post_key(hwnd, VK_SPACE, scan, key_up=False)
        time.sleep(0.06)
        ok_u = post_key(hwnd, VK_SPACE, scan, key_up=True)
        print(f"  down ok={ok_d}  up ok={ok_u}")
        time.sleep(2.0)

    print("\nDone. Did the quick-action fire on each PostMessage?")


if __name__ == "__main__":
    main()
