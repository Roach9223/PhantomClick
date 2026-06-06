# PhantomHID — USB HID keystroke bridge

A 100-line Arduino sketch that turns an ATmega32u4 dev board into a
real USB keyboard. PhantomClick sends commands over the serial port;
the board emits actual USB HID reports — indistinguishable from a
real keyboard at every layer of Windows / Raw Input / game-engine
input handling, because they ARE real USB HID reports from a real
USB device.

This is the only known path to drive RuneScape NXT keystrokes from
PhantomClick (NXT filters SendInput, Interception, *and* PostMessage
WM_KEYDOWN — see `project_nxt_keyboard_filter.md` in memory). It also
works for any other game with similar BotWatch-style filtering.

## What you need

- **Hardware:** any ATmega32u4 board — Pro Micro, Leonardo, Micro,
  Beetle. ~$5 for a clone Pro Micro.
- **Cable:** USB cable that fits the board (most Pro Micros are
  Micro-USB, Beetle is full-USB).
- **Software:** Arduino IDE 2.x (https://www.arduino.cc/en/software).

## One-time setup

1. Plug the board in.
2. Open Arduino IDE → Tools → Board Manager → install the relevant
   core (Sparkfun AVR Boards for Pro Micro, or Arduino AVR Boards for
   Leonardo / Micro).
3. Tools → Board → pick your specific board.
4. Tools → Port → pick the COM port the board enumerated as.
5. Open `phantomhid.ino` in this folder.
6. Click Upload (the right-arrow icon).

You should see "Done uploading" within ~10 seconds. The board's
power LED will stay on; some boards blink the TX LED briefly.

## Verify it flashed

Open a serial monitor (Tools → Serial Monitor) at 115200 baud,
line-ending = "Newline". Type `P` and press Enter. The board should
reply `OK PHANTOMHID v1`. Close the serial monitor before using
PhantomClick — only one process can hold the port at a time.

## Hook into PhantomClick

1. Install pyserial: `pip install pyserial`
2. Open PhantomClick → Settings → Behavior → Key input method.
3. Pick **Serial HID**.
4. In the COM port dropdown, pick the same port the IDE used.
5. Save (PhantomClick auto-saves on change).

That's it. KIND_KEY steps and key timers will now route through the
Arduino.

## Test before relying on it

Open Notepad, focus it, run a one-step recorder with a `KIND_KEY`
step bound to space. Spaces should appear. Then test in NXT — your
spacebar quick-action should now fire on every cycle.

If NXT still rejects keystrokes after switching to Serial HID, the
most likely cause is that NXT was launched **before** the Arduino
was plugged in, so NXT's startup device-handle cache doesn't include
the Arduino's HID handle. Quit NXT, plug the Arduino in (or leave it
plugged), then relaunch NXT.

## Protocol (for the curious)

Line-based ASCII over USB serial @ 115200 baud:

| Command         | Effect                              |
|-----------------|-------------------------------------|
| `D <vk>\n`      | Press down a Win32 virtual key      |
| `U <vk>\n`      | Release a Win32 virtual key         |
| `P\n`           | Ping; replies `OK PHANTOMHID v1\n`  |
| `X\n`           | Emergency release-all-keys          |

`<vk>` is the Win32 VK code in decimal (e.g. `32` for spacebar, `112`
for F1, `65` for A). The sketch translates Win32 VKs to Arduino
keyboard codes internally.

## Limits

- Modifier keys: Win32 distinguishes left/right, but for keys like
  Ctrl/Shift/Alt/Win the sketch always emits the *left* variant
  unless the host explicitly sends the right-side VK (0xA1, 0xA3,
  0xA5, 0x5C). This matches every Win32 modifier convention I've
  seen ship without bugs.
- The Arduino `Keyboard` library can hold up to 6 keys + modifiers
  simultaneously (one HID report's worth). Going past 6 keys
  silently drops the oldest — fine for any normal macro.
- USB HID reports drop on cable disconnect. PhantomClick will log
  "serial_hid send failed" if you unplug the board mid-session.

## Why not just use Logitech G HUB / Corsair iCUE macros?

Those firmware macros only fire when the *physical* key on the
device is pressed — there's no software API to trigger them
remotely. The Arduino is the only setup where the host can decide
when a real HID keystroke fires.
