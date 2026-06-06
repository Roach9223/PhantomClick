"""Smoke-test the PhantomHID Arduino bridge.

Pings the device, then fires three spacebar presses through the
``SerialHidBackend`` with a countdown before each so you can focus
Notepad to watch.

Run after flashing ``firmware/phantomhid/phantomhid.ino`` to your
ATmega32u4 board. Pass the COM port as the first argument, default
COM8.

If three spaces appear in Notepad the whole chain works and you can
switch PhantomClick to Behavior → Key input method → Serial HID.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, r"F:\.programs\AutoClicker")

import serial  # type: ignore

from modules import key_input_backend


def main() -> None:
    port = sys.argv[1] if len(sys.argv) > 1 else "COM8"

    # Probe via raw pyserial first so we get a clear error if the port
    # is in use / wrong / sketch isn't flashed.
    s = serial.Serial(port, 115200, timeout=1.5)
    time.sleep(2.0)
    s.reset_input_buffer()
    s.write(b"P\n")
    time.sleep(0.3)
    pong = s.read_all()
    s.close()
    print(f"ping {port}: {pong!r}")
    if b"PHANTOMHID" not in pong:
        print("FAIL: device didn't reply with PhantomHID handshake.")
        print("Flash firmware/phantomhid/phantomhid.ino and try again.")
        return

    backend = key_input_backend.get_backend("serial_hid", serial_port=port)
    print(f"backend.name={backend.name} available={backend.available}")
    if not backend.available:
        print(f"  init_error: {getattr(backend, '_init_error', '')}")
        return

    for i in range(3):
        print(f"\n[{i+1}/3] focus Notepad — firing space in", end=" ", flush=True)
        for n in range(4, 0, -1):
            print(n, end=" ", flush=True)
            time.sleep(1)
        print("FIRE")
        ok_d = backend.send(0x20, key_up=False)
        time.sleep(0.08)
        ok_u = backend.send(0x20, key_up=True)
        print(f"  down ok={ok_d}  up ok={ok_u}")

    print("\nDone. Did three spaces appear in Notepad?")


if __name__ == "__main__":
    main()
