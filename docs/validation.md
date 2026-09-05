# Reliability and usability validation

The September 2026 audit fixes cover settings validation and atomic saves,
responsive setup/editor layouts, one-click rehearsal, readiness messages,
background wiki image preparation, and safe bot-thread shutdown.

Verified on the development Windows workstation with Python 3.11.9 and
PySide6 6.11.0: **247 tests passed** (272.69 seconds) in the final handoff
regression run. The controlled desktop check passed all five stages in the
preceding Record/AI pass. The final PyInstaller executable passed startup and
close from an isolated scratch directory. Identical builds are available at
`dist/PhantomClick.exe` and `dist/audit/PhantomClick.exe`.

Correction: the prior claim that the existing user configuration was untouched
and needed no repairs was not a valid preservation check. The handoff reports
that configuration had been reset to defaults and was restored from the 22:04
backup. The full test suite was separately verified not to cause that reset.
This pass records the restored file's SHA-256 before and after validation and
runs packaged smoke tests from a separate scratch directory, never alongside
production configuration. The precise earlier reset trigger remains unverified.

Build SHA-256: `24c0acea87513e2b34db5e41b37c0f8100ba7d592f82d0479146e9dbc149c151`.

## Automated checks

`python -m pytest tests -q`

- Config: malformed JSON, invalid roots and values, independent mutable
  defaults, previous-file preservation on failed replacement, backup retention,
  retry after a save failure, and one-time migration of anti-cluster settings.
- GUI: build the actual Click, Record and AI pages at 960×640, 1200×720,
  1440×900 and 1920×1080. Assert editor geometry and control bounds; save render
  screenshots in pytest's temporary directory. Desktop capture, hotkey listeners
  and native window chrome are disabled for these offscreen checks.
- AI preparation: verify network calls happen away from the GUI thread, cached
  images do not download, failures are reported, and cancellation prevents late
  bot startup.
- Replay: decode saved synthetic PNG frames and run them through the Rust color
  detector and bot rules. Verify target loss/reacquisition, small-distractor
  rejection, negative screen-origin mapping, dry-run input suppression, and
  the consecutive-dry-tick stop limit. The actuator records requested inputs.
- Existing engine, geometry, key timer, hotkey, recorder, and Monitor access
  control regression tests remain part of the suite.

## Controlled desktop check

`python scripts/verify_click_target.py`

This explicitly interactive Windows check opens a target window and runs the
real click engine against it using temporary in-memory settings. It verifies:

1. Three actual mouse presses received inside the target area.
2. No additional presses while paused, followed by successful resume.
3. Hold while the target is minimized and reacquisition after it is restored.
4. Stop returning in under one second, with no subsequent clicks.
5. A Record macro delivering two clicks and A A A A B through Key, Pause and
   finite Loop steps, using the SendInput keyboard backend.

The test seeds its known window handle during the countdown because production
window discovery deliberately excludes PhantomClick's own process. Window
geometry and minimized-state checks use actual Win32 calls. This test therefore
checks an established window lock, not initial discovery of an external window.
The test never loads or saves the user's config. Its keyboard input goes to
its focused test window; do not change focus while the test is running.

See [Record and AI audit](record-ai-audit.md) for preset, rule-order, replay,
startup and retry-limit fixes, plus the compact Timing & Targeting panel.

## Remaining empirical validation

Synthetic scenes and a controlled window do not establish real-game success
rates or detection resistance. Before relying on unattended operation, record
representative frames from the intended task and measure false positives,
missed targets and recovery failures. Include lighting/animation changes,
occlusion, target movement, resolution and UI scaling changes.

Run longer sessions separately, including mixed-DPI displays, hardware keyboard
backends, LAN streaming and target-application updates. Those depend on hardware
and environments that automated offscreen tests cannot reproduce.

The focused refactoring separates persisted-setting validation, start readiness,
and background asset preparation. The click engine remains a larger component;
future extraction should preserve these integration checks rather than rewrite
working execution paths without behavioral evidence.


## Monitor-identity handoff follow-up

The restored production config had SHA-256
`28cd07caadd7294c7eab0688bb54286bd41f901c050e2cd2ae2271c82c37b7f5`
before this pass and after the isolated packaged startup/close test. A direct
read-only call to the validator reported zero repairs. No production config was
loaded into an interactive source-run App during this pass.

See [monitor identity](monitor-identity.md) for matching rules, legacy migration,
index fallback, and the remaining limitations of indistinguishable displays.
Both executable locations are refreshed from the tested build; runtime settings
and captures under `dist/` are preserved.
