// PhantomHID — USB HID keystroke bridge for PhantomClick
//
// Flash to any ATmega32u4-based board (Pro Micro, Leonardo, Micro,
// Beetle) so it enumerates as a real USB keyboard. PhantomClick talks
// to it over the serial port and the board emits actual USB HID
// keystrokes — indistinguishable from a real keyboard at every layer
// of the OS / Raw Input / game-engine stack, because they ARE real
// USB HID reports from a real device.
//
// Why this exists: RuneScape NXT (and a growing list of other anti-
// cheat-protected games) filter SendInput, Interception, and even
// PostMessage WM_KEYDOWN by correlating each keypress against a real-
// HID device handle in Raw Input. No software-only path beats that
// check. A second physical USB keyboard does, trivially. This sketch
// turns a $5 dev board into that second keyboard.
//
// Protocol (line-based ASCII over USB serial @ 115200):
//   D <vk>\n   press down a Win32 virtual key   (e.g. "D 32")
//   U <vk>\n   release a Win32 virtual key      (e.g. "U 32")
//   P\n        ping; device replies "OK PHANTOMHID v1\n"
//   X\n        emergency release-all-keys
//
// <vk> is the Win32 VK code in decimal. Translation to USB HID usage
// codes happens here so the Python side can stay agnostic and reuse
// the VK pipeline it already has from key_timer.py.
//
// Build target: Arduino IDE → Tools → Board → Sparkfun AVR Boards →
// Sparkfun Pro Micro 5V 16MHz   (or Arduino Leonardo / Micro / Beetle).

#include <Keyboard.h>

// Win32 VK code → Arduino Keyboard.h key constant.
// Values 0xB0..0xDA are the Arduino library's special-key constants
// (defined in HID/cores/Keyboard.h — KEY_LEFT_CTRL = 0x80, KEY_F1 = 0xC2,
// etc.). Returns 0 for unsupported VKs so the caller can fall back.
uint8_t vkToArduino(uint8_t vk) {
  // Modifiers — Win32 splits L/R; we always use left.
  if (vk == 0x10 || vk == 0xA0) return KEY_LEFT_SHIFT;
  if (vk == 0xA1)               return KEY_RIGHT_SHIFT;
  if (vk == 0x11 || vk == 0xA2) return KEY_LEFT_CTRL;
  if (vk == 0xA3)               return KEY_RIGHT_CTRL;
  if (vk == 0x12 || vk == 0xA4) return KEY_LEFT_ALT;
  if (vk == 0xA5)               return KEY_RIGHT_ALT;
  if (vk == 0x5B)               return KEY_LEFT_GUI;
  if (vk == 0x5C)               return KEY_RIGHT_GUI;

  // Whitespace / control
  if (vk == 0x20) return ' ';
  if (vk == 0x0D) return KEY_RETURN;
  if (vk == 0x09) return KEY_TAB;
  if (vk == 0x08) return KEY_BACKSPACE;
  if (vk == 0x1B) return KEY_ESC;

  // Editing pad
  if (vk == 0x2D) return KEY_INSERT;
  if (vk == 0x2E) return KEY_DELETE;
  if (vk == 0x24) return KEY_HOME;
  if (vk == 0x23) return KEY_END;
  if (vk == 0x21) return KEY_PAGE_UP;
  if (vk == 0x22) return KEY_PAGE_DOWN;

  // Arrows
  if (vk == 0x25) return KEY_LEFT_ARROW;
  if (vk == 0x26) return KEY_UP_ARROW;
  if (vk == 0x27) return KEY_RIGHT_ARROW;
  if (vk == 0x28) return KEY_DOWN_ARROW;

  // Locks
  if (vk == 0x14) return KEY_CAPS_LOCK;

  // Function keys F1..F12 (+ F13..F24 if the host VKs are sent)
  if (vk >= 0x70 && vk <= 0x7B) return KEY_F1 + (vk - 0x70);

  // ASCII letters / digits / common punctuation map straight through —
  // Keyboard.press accepts the ASCII code for these.
  if (vk >= 0x41 && vk <= 0x5A) return 'a' + (vk - 0x41);  // letters
  if (vk >= 0x30 && vk <= 0x39) return '0' + (vk - 0x30);  // digits

  // Numpad — using top-row digit equivalents so layout-independent.
  if (vk >= 0x60 && vk <= 0x69) return '0' + (vk - 0x60);  // numpad 0..9

  return 0;
}

// Small line buffer — protocol lines are tiny.
char buf[24];
uint8_t bufLen = 0;

void setup() {
  Serial.begin(115200);
  Keyboard.begin();
}

void processLine(const char* line, uint8_t len) {
  if (len == 1 && line[0] == 'P') {
    Serial.println("OK PHANTOMHID v1");
    return;
  }
  if (len == 1 && line[0] == 'X') {
    Keyboard.releaseAll();
    Serial.println("OK RELEASED");
    return;
  }
  if (len < 3) return;
  if ((line[0] != 'D' && line[0] != 'U') || line[1] != ' ') return;

  // atoi ignores leading whitespace and parses digits.
  int vk = atoi(line + 2);
  if (vk <= 0 || vk > 255) return;

  uint8_t k = vkToArduino((uint8_t)vk);
  if (k == 0) return;

  if (line[0] == 'D') Keyboard.press(k);
  else                Keyboard.release(k);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      buf[bufLen] = 0;
      if (bufLen > 0) processLine(buf, bufLen);
      bufLen = 0;
    } else if (bufLen < (uint8_t)(sizeof(buf) - 1)) {
      buf[bufLen++] = c;
    } else {
      // Overflow — discard line, wait for next newline.
      bufLen = 0;
    }
  }
}
