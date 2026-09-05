"""Smoke-test Interception keystroke delivery, slot by slot.

Why: PhantomClick's log says `backend=interception ok=True` for every
spacebar fire, but NXT doesn't react. We need to know whether the
driver is actually delivering events at all (independent of NXT).

This script tries every available keyboard slot 0..9 in turn. Before
each fire, it counts down 4 seconds so you can focus the target
window. After all driver attempts, it also fires once via SendInput
for A/B comparison.

Test plan:
  1. Open Notepad. Click into the empty document so the cursor blinks there.
  2. Run this script: `python scripts\\test_interception_send.py`
  3. During each 4-second countdown, click back into Notepad to refocus.
  4. After the script finishes, count how many spaces appeared in Notepad.

What the result tells us:
  * If at least one Interception slot put a space into Notepad: the
    driver works, and NXT is specifically filtering Interception events
    (or filtering events that don't come from the slot NXT recognizes).
  * If no Interception slot worked but SendInput did: the driver isn't
    actually injecting — the install or device binding is broken.
  * If nothing put a space in Notepad: focus wasn't on Notepad during
    the fire (most common reason — re-run and watch carefully).
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, r"F:\.programs\AutoClicker")

import interception  # type: ignore
from interception.inputs import _g_context  # type: ignore

from modules import key_input_backend


COUNTDOWN_S = 4


def countdown(label: str) -> None:
    print(f"\n[{label}] focus Notepad NOW — firing in", end=" ", flush=True)
    for n in range(COUNTDOWN_S, 0, -1):
        print(n, end=" ", flush=True)
        time.sleep(1)
    print("FIRE")


def fire_via_slot(slot: int) -> None:
    """Send a single space via raw _g_context against a specific slot."""
    from interception import _keycodes  # type: ignore
    from interception.constants import KeyFlag  # type: ignore
    from interception.strokes import KeyStroke  # type: ignore

    data = _keycodes.get_key_information("space")
    saved = _g_context.keyboard
    try:
        _g_context._using_keyboard = slot  # bypass setter validation
        down = KeyStroke(data.scan_code, KeyFlag.KEY_DOWN)
        up = KeyStroke(data.scan_code, KeyFlag.KEY_UP)
        _g_context.send(slot, down)
        time.sleep(0.08)
        _g_context.send(slot, up)
        print(f"   slot={slot} fired down+up")
    finally:
        _g_context._using_keyboard = saved


def main() -> None:
    interception.auto_capture_devices(verbose=True)
    print(f"\nauto-bound: keyboard={_g_context.keyboard}  mouse={_g_context.mouse}")

    populated = []
    for s in range(10):
        try:
            hwid = _g_context.devices[s].get_HWID()
        except Exception:
            hwid = None
        if hwid:
            populated.append(s)
            print(f"  slot {s}: {hwid[:80]}")

    print(f"\nWill fire space through every populated keyboard slot: {populated}")

    for slot in populated:
        countdown(f"slot {slot} (raw _g_context.send)")
        try:
            fire_via_slot(slot)
        except Exception as e:
            print(f"   slot={slot} FAILED: {type(e).__name__}: {e}")

    countdown("project SendInputBackend.send (LLMHF_INJECTED path)")
    s = key_input_backend.get_backend("sendinput")
    print(f"   send(0x20, down)={s.send(0x20, key_up=False)}")
    time.sleep(0.08)
    print(f"   send(0x20, up)={s.send(0x20, key_up=True)}")

    print("\nDone. Now look at Notepad and count the spaces.")
    print("  * Spaces from Interception slots => driver works for that slot")
    print("  * If only the SendInput one produced a space => driver is broken")
    print("  * If a slot worked here but NXT still ignores it =>"
          " NXT is filtering Interception events specifically")


if __name__ == "__main__":
    main()
