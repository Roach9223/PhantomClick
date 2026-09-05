# Record and AI audit

## What the modes do

**Record** is a macro builder, not automatic recording of your mouse and keyboard.
Add Click steps for fixed areas, Track steps for captured images, Color steps
for matching pixels, Key steps, pauses and loops. The sequence repeats until
stopped or a configured stop condition fires. Named presets now include Track
images and restore independent copies when loaded.

**AI** evaluates screen-based rules in priority order and runs the first match.
It supports scripted bots and authored procedures. It does not learn a task
from watching you. Correct captures, search areas, inventory calibration and
an input backend accepted by the target application are required.

Dry run evaluates detections and logs proposed actions without sending input.
Replay tests saved frames and always disables input, even if the app switch
is turned off. A script with `Bot(dry_run=True)` also enforces dry run; the UI
now reports that restriction instead of incorrectly claiming keys are firing.

## Changes

- Replaced the stretched Cadence card with a fixed 166-pixel Timing & Targeting
  card: interval, curve, realism and explicit anti-cluster state/radius.
  Clicking interval or anti-cluster opens the relevant settings. Current Run
  uses the available room for step/tick progress, clicks and recovery counts;
  it hides on shorter layouts.
- Record ignores disabled steps during readiness checks and rejects broken
  loop targets. Repeating keys honor pause; failed key dispatch stops the
  sequence with an error instead of silently advancing.
- Presets embed PNG templates, save atomically and reject invalid step entries
  instead of silently loading a partial macro.
- AI preserves cancellation during startup, finishes cleanly on backend setup
  errors, stops after five consecutive capture failures, and ignores stale
  completion events from an earlier run when a new run has started.
- Acadia banking now precedes chopping, requires inventory calibration and a
  `bank_open_acadia` snapshot, and loads preset 1 after detecting the open bank.
  A full inventory without a bank target stops with a setup error.
- Bundled bank-preset retries stop after three unsuccessful attempts. Fishing
  stops after ten recasts without observed animation, covering a failure that
  repeated clicks could hide from the no-click watchdog.

## Evidence and effectiveness

The controlled Windows test delivered the exact Record sequence of two clicks
and A A A A B through real input, including pauses and a finite loop. It also
verified click limits, pause/resume, minimized-target hold/recovery and stop.
Synthetic images verified Track movement/loss/reacquisition and Color matching,
including alternate colors and negative display coordinates. AI replay tests
exercise saved PNG decoding, detection, rule execution and input suppression.
Regression tests cover presets, readiness, startup/cancellation, repeated
starts, capture failure and bundled rule priorities/retry limits.

Record is suitable for predictable workflows whose targets remain identifiable.
AI can react to changing screen states, but its reliability depends on the
quality of each bot's detections and calibration. The bundled examples remain
in dry run and need target-specific setup. Acadia still has sample colors and
large fixed search rectangles; these must be tuned for the actual display.

No representative game recording or specified live target was supplied for
this audit. These tests therefore do not establish a 100% success rate in the
target application, long-session reliability, or compatibility with every
keyboard backend. The next useful validation is a labeled replay containing
successful actions, target loss, full inventories and banking failures, followed
by a supervised live session measuring false matches and missed actions.

From a user perspective, the compact panel gives anti-cluster a clear status
without dominating the screen. Record's manual setup and AI's dry-run state
are now explained directly. AI still exposes substantial authoring complexity;
per-bot setup wizards and visible required-capture checklists are the strongest
remaining usability improvements.
