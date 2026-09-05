# PhantomClick: Human-Like Auto Clicker

## What Is This?

A Windows desktop auto-clicker built around the idea that *what looks human is human enough*. The cursor physically moves along curved paths, dwells, jitters, fatigues, and occasionally takes breaks; clicks land at randomized points inside a user-drawn area; timings are sampled from log-normal distributions instead of uniform ones. The user controls all of this from a dark, wide-format PySide6 Qt window with three top-level modes:

- **Click**: pick one area on screen and the engine clicks inside it forever.
- **Record**: build an ordered sequence of steps (click / track / color / key / pause / loop) that runs top-to-bottom and loops.
- **AI**: run a rule-based RuneScape bot from `ai/tasks/library/`. Bot rules dispatch through PhantomClick's humanizer for clicks and the Arduino HID backend for keystrokes (the only NXT-resistant keyboard path).

Automation runs locally and offline by default, with no telemetry or auto-update. The opt-in LAN Monitor and optional runescape.wiki item-image downloads are the network features; both default off.

---

## Phase 2 Hardware Roadmap (long-term)

A pro-grade RS3 bot stack is on the roadmap, all hardware on hand: **Captain DMA Fuser** (Main PC PCIe, reads RAM directly, invisible to NXT), **Elgato PCIe capture card** (Bot PC, HDMI passthrough, Main PC sees only a monitor), and **KMBox NET** (USB to Main PC for HID, Ethernet to LAN for commands, looks like a real mouse + keyboard).

The bot will live entirely on a separate Bot PC. Main PC will see: a monitor, a HID device, and a generic PCIe card. No software touches RS3.

Phase 2 is a hobby-pace multi-month build, gated on Phase 1 (color detection recovery) completing first. Phase 3 is RS3 NXT offset reverse engineering, gated on Phase 2 hardware being end-to-end verified. See **`gameplan.md`** for the full roadmap and **`docs/wiring_diagram.md`** for hardware topology.

When making architectural changes, check that they don't conflict with the planned Bot-PC-side mode: anything that hardcodes "engine runs on the same machine as the game" or "mss is the only frame source" will need rework in Phase 2.

---

## Tech Stack

- **Language:** Python 3.11 (pinned: the bundled `rs3vision/_rs3vision.pyd` Rust core is ABI-bound to 3.11)
- **GUI:** PySide6 / Qt 6.6+ (charcoal-slate palette, ice-blue `#7CC4F2` selection accent, green `#4ADE80` for live state, Barlow labels over JetBrains Mono values)
- **Mouse:** `pynput` via humanized Wind/Hooke paths today; **KMBox NET** over LAN is the planned Phase 2 input path (NXT-invisible HID controller, see `gameplan.md`).
- **Keyboard:** `modules/key_input_backend.py`, selected by the `key_input_method` config key (`auto` | `sendinput` | `interception` | `serial_hid`). Serial HID drives an Arduino Leonardo running the PhantomHID firmware in `firmware/phantomhid/`; it is the only software path NXT does not filter. Phase 2 adds `kmbox_net` as a further option that handles mouse + keyboard from off-machine.
- **Screen capture / template matching:** `mss` + OpenCV (`cv2.matchTemplate`, multi-scale `TM_CCOEFF_NORMED`); AI mode also uses a Rust-backed vision library (`rs3vision`) for CTS color clustering + DTM template matching.
- **Numerics / image:** `numpy`, `Pillow`
- **AI mode:** RS3 bot framework merged in at `ai/`; Rust vision core ships at `rs3vision/`. `@bot.rule` decorator pattern, BotRunner on a QThread.
- **Packaging:** PyInstaller (single .exe)
- **Target OS:** Windows 10/11

---

## Project Layout

External documentation pointers:
- **`gameplan.md`**: durable Phase 1 / Phase 2 / Phase 3 roadmap, hardware inventory, considerations.
- **`docs/wiring_diagram.md`**: Phase 2 hardware wiring topology (Mermaid diagram + ASCII fallback + cable BOM).
- **`phantomclick.log`**: runtime log file at repo root; instrumented `[find_any_color/<label>]` lines surface color-detection diagnostics.

```
AutoClicker/
├── main.py                  # Entry point (sets DPI awareness, then imports the App)
├── app.py                   # Thin shim: `from ui.app import run` so `python main.py` works
├── config.json              # Persisted user settings (created on first save; gitignored)
├── gameplan.md              # Long-term roadmap (Phase 1/2/3), see above
├── requirements.txt         # Runtime deps (Python 3.11, numpy<2); requirements-build.txt adds PyInstaller
├── build.ps1                # Finds Python 3.11, installs deps, runs PyInstaller with PhantomClick.spec
├── PhantomClick.spec        # PyInstaller spec (onefile, splash, bundled ai/ + rs3vision)
├── docs/                    # Project docs (wiring diagram, hardware setup)
├── packaging/               # phantomclick.ico, splash.png and the scripts that generate them
├── scripts/                 # probe_*.py: manual input-backend probes; verify_click_target.py: interactive engine check
├── pytest.ini               # testpaths = tests, so the probes in scripts/ are never collected
├── tests/                   # pytest suite; conftest.py isolates config_io._config_path per test and fails the
│                            #   session if the real config.json changed (a tooling pass once wiped it to defaults)
├── templates/               # Per-step Track templates (`<step_id>.png` + `<step_id>_view_<uuid>.png`); gitignored
├── assets/                  # Screenshots and design sources; gitignored, not used at runtime
├── ui/                      # Qt UI layer
│   ├── app.py               #   Main window: NavRail + TopBar + page stack, hotkeys, engine glue
│   ├── theme.py             #   Colors, fonts, spacing tokens (slate, ice-blue + green accents)
│   ├── topbar.py            #   Pinned top bar: brand, status pill, START/STOP, Esc hint, Ctrl+K, overlay toggle
│   ├── command_palette.py   #   Ctrl+K command palette (search + execute any registered command)
│   ├── engine_bridge.py     #   Engine-thread to GUI-thread marshalling (QMetaObject.invokeMethod)
│   ├── widgets/             #   Reusable widgets: NavRail, Card, Section, Field, Expander,
│   │                        #     StatusPill, RangeSpinSlider, GroupHeader/SettingsGroup/SettingsRow
│   ├── pages/               #   One page per nav item (Click, Record, AI, Hover, Behavior,
│   │                        #     Hotkeys, Timers, Stats, Monitor, Settings, Help)
│   ├── cards/               #   Page-internal sections (steps.py for the Record body, ai.py for AI, ...)
│   ├── overlays/            #   Fullscreen Qt overlays: ZoneDrawer, ZoneOverlay, ColorPicker, click marker
│   ├── config_io.py         #   load_config / save_config (atomic, rolling config.json.bak) + auto-migrations
│   ├── config_validation.py #   validate_config: repairs invalid values on load, keeps unknown keys
│   ├── readiness.py         #   readiness_message / preflight_failures: why START is blocked, incl. missing monitor
│   ├── monitor_identity.py  #   screen identity (name / model / serial / geometry) next to the index; strict matching
│   ├── asset_preparation.py #   cancellable background wiki-image fetch before an AI run
│   └── monitor_server.py    #   stdlib HTTP + MJPEG server backing the Monitor tab
├── modules/
│   ├── clicker.py           # Click engine (threading, randomization, mode dispatch,
│   │                        #   tracker integration, fatigue, watchdog, recheck-before-click)
│   ├── recorder.py          # RecorderStep dataclass + KIND_CLICK / KIND_TRACK / KIND_COLOR /
│   │                        #   KIND_KEY / KIND_PAUSE / KIND_LOOP + JSON (de)serialization
│   ├── sequence_library.py  # Named Recorder presets saved as JSON under <config_dir>/sequences/
│   ├── tracker.py           # TemplateTracker (multi-scale matchTemplate, thread-safe state)
│   ├── zone_selector.py     # Zone dataclass (rect / circle / polygon); GUI-free
│   ├── hotkey_manager.py    # Global Start / Stop / Pause / Capture hotkey listener (never logs raw keys)
│   ├── key_timer.py         # KeyTimer dataclass + combo parser + run_timer_loop()
│   ├── key_input_backend.py # Pluggable keystroke sender (SendInput / Interception / Serial HID)
│   └── stats.py             # Per-session counters (total, cpm, last pos, elapsed)
├── utils/
│   ├── humanizer.py         # Wind/Hooke move, click timing, drift, overshoot
│   ├── fatigue.py           # Wall-clock fatigue multiplier + click-count "break burst" scheduling
│   ├── idle_wanderer.py     # Cursor wander between clicks (in-zone or whole-screen)
│   ├── paths.py             # writable_root() / bundled_root() for dev vs. frozen exe
│   ├── window_finder.py     # ctypes EnumWindows + WM_CLOSE (Monitor "Close RS")
│   └── logger.py            # Rotating file logger (phantomclick.log next to the exe)
├── ai/                      # RS3 bot framework (merged from RS3_AI)
│   ├── bot/                 #   @bot.rule decorator, BotRunner QThread, dispatch loop, step compiler
│   ├── tasks/library/       #   Bundled bots (`*.task.yaml` + companion `.py`)
│   ├── graph/               #   World-graph navigation (lodestones, edges, pathfinder)
│   ├── algorithms/          #   Shared scanning helpers (CTS, DTM, OCR, minimap)
│   ├── input/               #   InputBackend Protocol + ClickerActuatorBackend bridge
│   ├── captures/            #   Global capture library (colors, DTMs, ROIs, snapshots)
│   └── wiki/                #   Cached lookups for item / monster metadata
├── rs3vision/               # Rust vision core (see rs3vision/README.md for source + rebuild)
│   └── _rs3vision.pyd       #   Prebuilt CTS + TPA + OCR module (Python 3.11, numpy 1.x)
└── firmware/phantomhid/     # PhantomHID Arduino sketch for Leonardo (NXT-resistant keystrokes)
```

---

## Modes

### Click (single-zone)
The simplest mode and the one to use when one button keeps appearing in the same place.

**Window lock.** Every click zone (Click mode, Click steps, Color click areas) can be anchored to the top-level window it was drawn over. With `zone_lock_default: "window"` (the default) the draw flow records the window's title, class and DIP rect in the zone as `"lock": {"mode": "window", "title": ..., "cls": ..., "anchor_rect": [x, y, w, h]}`. Before every click the engine resolves the zone through `modules/zone_lock.py`, translating and scaling it to the window's current rect, so a dragged or resized game window keeps the zone on target. If the window is gone or minimized the engine holds: it toasts `TARGET LOST · <title>`, waits on the stop event in 0.5 s steps, and resumes with `TARGET REACQUIRED` when the window returns. It never clicks into whatever replaced the window. Zones without a `lock` key stay in screen coordinates; hover zones drawn with `zone_lock_default: "window"` get a lock like any other zone. **The LOCK row is also a window picker** (`ui/widgets/lock_control.py`): with WINDOW selected, a combo lists every lockable top-level window as `Title · exe` (`utils/window_finder.list_lock_targets`, re-enumerated each time the list opens, front-most first, minimised included), with the locked window selected. Picking another one emits `windowChosen` and the owner calls `modules/zone_lock.retarget_lock(zone, info)`, which rebases the zone from the old anchor into the new window's rect so it keeps the same relative place (switching from one game client to another lands on the same corner), or, for an unlocked zone, keeps the screen position and adds the anchor. The overlay outline and the deck reticle draw the resolved zone and turn amber while holding. The user draws a rectangle / circle / polygon zone, picks a min and max delay range, and the engine clicks forever inside that zone with realism behaviors layered on top. Persisted as `zone` + `min_delay` / `max_delay` in `config.json`.

### Record (sequenced)
An ordered list of `RecorderStep`s that fire top-to-bottom then loop. Six step kinds, all live in the same list:

| Kind | What it does | Required data |
|---|---|---|
| `KIND_CLICK` | Click in a fixed zone N times before advancing | `zone` |
| `KIND_TRACK` | Follow a captured-template target (with optional alternate views for rotation / camera-angle changes) and click on it as it moves | `template_path` + `capture_rect` (physical pixels, tagged by `capture_rect_space`; steps saved before the tag existed load as `"dip"` and are converted on use); optional `extra_template_paths` / `extra_template_sizes` |
| `KIND_COLOR` | Eyedropper picks a target color from a frozen-screen overlay; the engine clicks any pixel within `color_tolerance` of that color (RGB euclidean) wherever it appears. Multiple colors per step are supported via `color_extra_rgbs`, any pixel matching ANY accepted color counts as a match (useful for buttons with gradients / anti-aliased edges). An optional `step.zone` (rect / circle / polygon, drawn from the body's "Set click zone" button) restricts where the engine looks for matches, critical when the same color appears on the HUD as well as the clickable target | `color_target_rgb` (+ `color_tolerance`, default 30; `color_search_rect` bounds the per-cycle scan to the picked monitor; optional `color_extra_rgbs` list for multi-color matching; optional `zone` for click-area scoping) |
| `KIND_KEY` | Sends a keystroke / combo (`f1`, `ctrl+shift+z`, …) through the backend chosen by `key_input_method`. No cursor movement, no click. Use for hotbar abilities or chatbox commands inline with the sequence | `key_combo` |
| `KIND_PAUSE` | Wait `delay_min`–`delay_max` seconds, no click; cursor still drifts | nothing (uses `delay_*`) |
| `KIND_LOOP` | Jumps execution back to an earlier step (forever, or N more times before continuing) | `loop_target_step_id` (+ `loop_count`, 0 = forever) |

Color steps default to scanning only the monitor where the color was picked, so multi-monitor setups don't pay for the full virtual desktop on every cycle; legacy steps without a `color_search_rect` fall back to the full virtual screen. `color_search_rect` is stored in physical (mss) pixels; `step.zone` is in DIPs like every other zone, and the engine converts between the two inside `_find_color_target`.

By default the engine wraps from end-of-list to step 0 (modular `_step_idx` advance), so a sequence with only Click / Track / Pause steps loops the whole list forever. A `KIND_LOOP` step lets the user instead split the sequence into a **setup phase** (steps before the loop, fired once) and a **repeating phase** (the section between the loop's target and the loop itself, fired forever or `loop_count` more times). The recorder tab surfaces the wrap behavior in a footer line under the steps list (*"↻ After step N, loops back to step 1 forever"*) so it's never invisible.

Steps are stored as `recorder_steps` in `config.json` via `RecorderStep.to_json` / `from_json` (which also handles legacy `is_pause: bool` migration → `kind: str`).

Track-step templates live as PNGs at `templates/<step_id>.png` (relative path stored in `step.template_path`). Duplicating a track step regenerates its `step_id` so a later "Recapture" doesn't overwrite the original's PNG. Removing a track step deletes its primary PNG plus every extra-view PNG that no other step still references.

**Alternate views**: a track step can hold any number of extra captures of the same target via the row's "+ Add view" button (stored at `templates/<step_id>_view_<uuid>.png`). The engine matches the primary plus every extra against the screen each frame and uses whichever scores highest, the click box is sized by the *winning* view's dimensions, not the primary's, so a side-view match isn't misshaped by front-view geometry. This handles 3D NPCs / camera rotation / pose changes that a single template can't.

`mss` capture uses `monitors[0]` (the virtual screen union) rather than `monitors[1]` (primary only) so the capture bytes always cover wherever the user drew the box on a multi-monitor setup.

### AI (rule-based bots)
The third top-level mode. The user picks a bot from `ai/tasks/library/` (each bot is a `*.task.yaml` manifest + companion `.py` script with `@bot.rule`-decorated handlers), then START runs the bot tick loop on a `BotRunner` QThread.

Per tick, `BotRunner` evaluates every registered rule in priority order. A rule is a function `(world: WorldState) -> RuleAction | None`; the first non-None action wins, gets dispatched through the configured `InputBackend`, and the loop sleeps until the next tick.

**Vision.** Bots use the `rs3vision` Rust core (CTS color clustering + DTM template matching) for fast on-screen detection, plus `algorithms/` helpers for OCR, minimap reads, and inventory scans.

**Input bridge.** `ai/input/clicker_actuator.py` (`ClickerActuatorBackend`) implements the framework's `InputBackend` Protocol on top of PhantomClick's primitives: clicks go through `humanizer.move + click` (so they look human and respect realism), keystrokes go through `modules/key_input_backend.py` (so AI bots get the same NXT-resistant Arduino HID path that recorder KEY steps use).

**Why merged.** RS3_AI had its own placeholder humanizer and no NXT-safe keyboard path. PhantomClick already had both. Merging meant the bot framework inherits PhantomClick's realism + Arduino HID for free, and PhantomClick gains the rule-based bot mode as a peer to Click and Record.

Persisted as `ai_bot_slug`, `ai_tick_rate_hz`, `ai_monitor`, `ai_dry_run` in `config.json`. `ai_dry_run` defaults to true, and a script's `Bot(dry_run=True)` is a floor: the effective value is the config flag OR the script flag, so a bot can't be forced live from the UI while its author still has it in dry run. A bot running keeps the topbar in the running state (START disabled, STOP enabled, pill shows the tick and rule) and Esc stops it, exactly as for the click engine.

The optional item-icon fetch from runescape.wiki is gated by `ai_wiki_fetch_enabled` (default false, toggle on the Settings page). With it off, no outbound request is ever made.

---

## Monitor (LAN screen + remote control from phone)

A separate **Monitor** tab opt-in by the user. Two stages, both off by default:

1. **Enable streaming**: spins up a stdlib `ThreadingHTTPServer` on `0.0.0.0:<monitor_port>` (default 8765). A background thread captures the picked monitor at the configured FPS (default 15), downscales to at most 1920 px wide (configurable; 0 = native), JPEG-encodes via Pillow at quality 85 (configurable), and caches the bytes. Endpoints:
   - `GET /`: embedded HTML page (live `<img>` of `/stream`, status panel polling `/status`, control buttons gated on the remote-control toggle).
   - `GET /stream`: `multipart/x-mixed-replace` MJPEG.
   - `GET /snapshot.jpg`: single JPEG (lower-bandwidth alternative).
   - `GET /status`: JSON with state, phase, phase_label, phase_remaining, stats snapshot, remote_control flag, AI runner summary.
   - `GET /ai/bots`: JSON list of the bots in `ai/tasks/library/` (slug, name, goal).

2. **Allow remote control**: additionally permits `POST /control/start`, `POST /control/stop`, `POST /ai/select` (body `slug=<bot>`; the cfg write is marshalled to the GUI thread), and `POST /control/close-window` (which sends `WM_CLOSE` to any visible top-level window whose title contains "RuneScape", via `utils/window_finder.py`). The close endpoint also requires `confirm=true` in the form body so an accidental tap can't kick the user out of the game. WM_CLOSE is a window-level message and isn't filtered by NXT (which filters keyboard injection only).

**Auth.** Random URL token (`secrets.token_urlsafe(24)`), persisted in `config.json` as `monitor_token`. Generated on first enable. All endpoints check `?token=<value>` (or the `pc_token` cookie set by `/`). Comparison is constant-time (`hmac.compare_digest`). Rotating the token via the "Regenerate token" button invalidates every existing URL.

**Logging.** Every accepted control action emits a line to `phantomclick.log`: `monitor_control action=start client=192.168.1.42 ok=True`. The token is never logged: the start line reports only the port and whether a token is set, and request lines have `token=` redacted. POST bodies over 64 KB get a 413 before they are read.

**Threats out of scope (LAN-trust model).** No SSL, no rate-limiting, no IP allowlist. The token is the access control. Anyone on the same Wi-Fi who has the URL can view AND (if remote control is on) control. The card text says so plainly.

`MonitorServer.start()` is idempotent, it stops any running instance first, so port/FPS changes restart the server cleanly. `MonitorServer.stop()` is wired into `App.closeEvent` so the listening port is freed before the process exits.

---

## The Engine (`modules/clicker.py`)

Single-threaded event loop running in a daemon thread, plus a watchdog thread for the corner-emergency-stop. All sleeps go through `threading.Event.wait()` so Stop is instant.

Per-cycle dispatch in `_run`:
1. **Recorder mode**: `_peek_recorder_step()` returns the current step.
   - `KIND_PAUSE` → `_human_delay()` + `_wait_with_wander()` + advance.
   - `KIND_TRACK` → `_activate_track_step()` (load PNG into shared tracker, push per-step settings) → poll `_tracker_zone()` until locked → use that zone for this cycle's target.
   - `KIND_COLOR` → `_find_color_target()` snapshots `color_search_rect` (the picked monitor) via a persistent engine `mss.mss()` handle, masks with `cv2.inRange`, and picks a random match via `cv2.findNonZero`, used as a 4×4 cycle zone around the matched pixel.
   - `KIND_LOOP` → resolve `loop_target_step_id`, decrement per-run iteration counter, jump.
   - `KIND_CLICK` → use `step.zone`.
2. **Clicker mode**: use `self.zone`.
3. Sample target inside the zone (Gaussian biased toward center via `Zone.random_point()`).
4. `_anti_cluster()` repels target away from the last 10 click positions.
5. `_jitter()` adds ±1–3 px noise.
6. `humanizer.move()` traces a Bezier path with overshoot/jitter (controlled by realism dial).
7. **Recheck-before-click** for track steps: re-read tracker state after the move; if the target has drifted more than ~40 % of the template's smaller dimension, do a quick straight-line correction. If lock is lost mid-move, abort the click rather than firing on stale pixels.
8. `humanizer.click()` fires the actual button (uses `pynput`).
9. Stats update; click-count counter increments; advance step if reached.
10. `_post_click_micro_wander()` always drifts the cursor 5–30 px after each click so it never freezes on the click point.
11. Periodic `_maybe_distraction_spike()` ("looked away" pause) and `Fatigue.maybe_break()` ("break burst" sleep).

Tracker template + locate loop is **owned by the App**, not the engine, so the user gets a live preview overlay even while idle. The engine just reads `tracker.snapshot_state()` and mutates the same shared TemplateTracker via `_activate_track_step()`. When the engine is running, the App's preview loop and the engine's reads coexist on the same tracker instance.

---

## GUI Architecture (`app.py` + `ui/`)

### Command deck shell (default since September 2026)

`ui_shell` in `config.json` selects the window layout. `"deck"` (default) builds the command deck in `ui/deck/`; `"classic"` builds the older NavRail + TopBar + page stack described below, which stays as a fallback and is smoke-tested alongside the deck.

The deck is one screen, no page switching. `ui/deck/shell.py` composes it:

- **Vocabulary (September 2026).** One word per concept, everywhere the user can read it: the thing clicks land in is a **zone** (never "area"); the engine is **STANDBY / ARMING / RUNNING / HOLD** (`deck/common.py` `state_word`, never "idle" or "active" on screen); the halt is **STOP** (the header button, "ESC STOPS", "CORNER STOP"; never "abort"). Config keys keep their old names (`corner_abort_enabled`).
- **Trust band** (`shell.py` `TrustBand`): an 18 px hairline band above the header reading `LOCAL · OFFLINE · NO TELEMETRY`, or `LOCAL · LAN MONITOR ON · NO TELEMETRY` in amber while the Monitor server streams. It is the app's one promise, in the place a console carries its marking.
- **Header** (`header.py`): Barlow wordmark at `SIZE_TITLE`, SESSION and STATUS chips (STATUS reads STANDBY / ARMING / RUNNING / HOLD / TARGET LOST; RUNNING is green), the **pane toggle** (`EditorToggle`, a checkable pencil-icon button that shows or hides the editor pane; ice outline while closed, solid ice while open, and it leads the right-hand cluster just left of the subsystem strip so it is the first thing to press; labelled by mode from `PANE_LABELS`: SETUP in Click, STEPS in Record, BOT in AI; Ctrl+E and the palette's "Toggle the setup / steps / bot pane" command flip it), the **subsystem strip** (`SubsystemStrip`: HID · CAP · HOT · LAN squares, green nominal / amber degraded / red fault / grey off-by-design, each with a plain-language tooltip and a click that opens the page where it is fixed; HID reads the cached probe on `right.engine_status.hid_state()`), icon buttons (monitor, overlays, settings, fullscreen), START / STOP (still exposed as `app.start_btn` / `app.stop_btn`) and "ESC STOPS". **START dims while setup is incomplete**: `DeckShell.tick` feeds `readiness()` into `header.set_start_blocked(reason)`, which disables the button and puts `Blocked: <reason>` in its tooltip. There is no readiness banner; the reason's other home is the SEQUENCE panel footer.
- **Left column** (`columns.py`): MODES (Click / Record / AI rows; clicking sets `active_mode`), SEQUENCE (see next paragraph), EVENT LOG (below, see next paragraph; SEQUENCE and the log split the flex space and each keeps at least five rows), SYSTEM (input backend, capture source, DPI scale, lock state, hotkeys, BUILD from `ui/_build.py` with a `.git` fallback).
- **Sequence panel is a control.** `SequencePanel` builds a list of `RowSpec`s per tick (key, text, checked, dot, active, dim, strike, toggle, click) and rebuilds its `SeqRow` widgets only when the set of `(key, toggle, click)` changes; text and colours refresh in place, so a 100 ms tick never re-creates widgets. Interactive rows get a pointing cursor and a `SURFACE_HIGH` hover fill; state rows (ENGINE, TARGET) stay inert. Click mode: `ZONE DRAWN` redraws the zone, `WAIT` (the interval) opens the editor pane and focuses the timing card, `NEXT BREAK` toggles `break_bursts_enabled`, `STOP AFTER` toggles `stop_after_minutes_enabled` (when a minutes value is set, else `stop_after_clicks_enabled`), both through `save_config_later` (which also pushes to the engine) plus `behavior_card.refresh_advanced()` so the Behavior switches agree. Record mode: rows read `01  CLICK  <label or X 0640 Y 0412>`, the 11 px square flips `step.enabled` (`save_steps_later()` + `record_mode_tab.render_all()`), the text selects the step (opens the pane, `record_mode_tab.select_step(step_id)` expands the card and scrolls it into view), disabled rows are `TEXT_DISABLED` and struck through, the running step keeps its green dot, and a ghost `+ STEP` in the panel title pops the record tab's add menu (`record_mode_tab.show_add_menu()`). AI mode: `TICK RATE`, a `DRY RUN` row whose square toggles `ai_dry_run` through the AI card's switch (so a running bot gets `set_dry_run`), then the last fired rules keyed by position. Click and Record also list key timers, as `KEY CTRL+Z  IN 04:12` countdowns from `clicker.key_timer_countdowns()` while running and as interval ranges while idle; clicking one opens the Timers page.
- **Event log.** `app.event_log` is a 200-entry `EventLog` ring buffer (`deck/common.py`). `clicker.on_event(kind, text)` fires on the engine thread and is marshalled through the queued `_engineEventFired` signal, the same pattern `on_click_fired` uses; every click also lands as `CLK  X 0640 · Y 0412`, and bot start / stop is logged from `engine_bridge.on_bot_running_changed`. The panel paints rows itself (`HHMMSSZ  KIND  text`, mono 10.5 px, kind coloured: CLK bone, WDR / BREAK / DISTR / HOLD amber, LOST / WDOG red, START / RESUME green, the rest secondary), newest at the bottom with auto-scroll that pauses when the user scrolls up. CLEAR in the panel header empties the buffer.
- **Center**: a horizontal `QSplitter`. Left: the live viewport (`viewport.py`, a `CaptureWorker` QThread grabbing the target monitor at 5 fps, with rulers, corner brackets (green while running), reticle, recent clicks, CPM and NEXT readouts and the mg63 countdown dial painted over it) above the control deck (`control_deck.py`: nudge pad, HOLD / TEST CLICK / the mode-aware screen action, MIN / MAX / REALISM vertical sliders, L / R / M). **The deck has no second START or STOP**: the header pair is the only one (the round ENGINE button, RUN CLICKS and ABORT were removed in September 2026 as duplicates). **Viewport fit**: the frame letterboxes to its aspect unless the bands would exceed 25 % of the height (editor pane open on a wide monitor), in which case it covers the area, scaled to the height and cropped around the zone; `Viewport.cover_mode()` reports which; rulers, clicks and the reticle clip to the visible part. Right: the **editor pane**, the editor for the active mode (Click page, Record tab, AI page; each scrolls on its own) so clicks and steps are edited on the same screen as the live view. The header EDITOR button shows or hides it; `App.show_page` for a mode id opens it. Minimums: viewport side 520 logical px, pane 480. Persisted as `deck_editor_open` (default true) and `deck_splitter` (two ints; null means 56 / 44, re-applied at any window size until the user drags the handle).
- **Editor pane pages are built for the pane** (480 to 700 px, September 2026 refresh). Each starts with an `EditorHeader` (uppercase title, one-line hint, trailing controls) and stacks one column of cards. Click (`ui/cards/click_mode.py`): `ClickZoneCard` = one-line zone summary, DRAW ZONE (the only primary button) + CLEAR, then SHAPE / LOCK / ON SCREEN rows; the ON SCREEN switch and opacity slider drive the on-screen outline and mirror the header eye button through `App.set_overlay_visible`. `TimingCard` = readout, log range slider, a 2 x 2 grid of one-line `PresetCard`s, BUTTON and PATTERN rows, inside the collapsed "Timing details" expander (see Pane roles below). Record (`ui/cards/record_mode.py`): header with a step-count pill, the ice ADD STEP menu button and a `···` overflow menu (save / load / clear all / clear log), an `EmptyState` with an add CTA when there are no steps, the step cards, and the loop footer. The kind filter is gone. Step cards (`ui/cards/steps.py`) keep a one-line header: chevron, number, kind, elided label, warning, enable switch and one `···` menu for move / duplicate / remove; the Click body stacks CLICKS over the delay slider. AI: `EditorHeader`, capture buttons wrap three per row (`_WrapRow`), calibration readouts sit under their labels. Every mode page's minimum width must stay under the pane floor; measure with `scroll.widget().minimumSizeHint()` when adding rows.
- **Pane roles (September 2026 audit).** The pane is one-time setup in Click, the whole editor in Record, and the bot picker in AI. `DeckShell._pane_needed` opens it automatically when a mode cannot proceed without it: Record with zero steps, AI with no bot slug, custom bot or active bundle, Click with no zone (the pane's DRAW ZONE is the primary way to draw one; the deck's DRAW ZONE action and the MISSION row are the shortcuts). Click's page is `ClickZoneCard` plus a collapsed "Timing details" `Expander` around `TimingCard` (`ClickPage.reveal_timing()` opens it for the deck's INTERVAL row); realism is not on the Click page, the deck slider and the Behavior page are its two homes. Step bodies lead with the target or key and the timing; the label, and for Track / Color the resilience section, sit in a collapsed "Details" expander at the foot (`StepRowBuilder._details_expander`, open state keyed `<step_id>:details` in `_advanced_open`). Picking a step from the SEQUENCE panel calls `expand_only`, so one card is open. The control deck's screen button (`ControlDeck._capture_target`) serves the selected, else expanded, else first Track / Color / Click step and relabels itself CAPTURE / PICK COLOR / DRAW AREA; in Click mode it draws the click area. The AI page opens as a consumer view (Bot, Config, Live); the header's AUTHOR TOOLS switch (`ai_author_tools`, default false) reveals Captures, Global capture library, Rules, Calibration and Log. The in-GUI authoring section still follows the bot picker, and the decision to merge or drop that second step DSL is still open (see Known gaps).
- **Right-click menus** (`ui/deck/context_menus.py`, September 2026). The live viewport's menu offers "Put a 60 x 60 click zone here" at the DIP under the cursor (`place_click_area`: sets the Click zone, or in Record mode the selected / expanded Click step's zone, else appends a Click step), draw on screen, an Add step submenu in Record mode, the outline toggle, Zoom, Target monitor and opening the pane. `Viewport.widget_to_dip` is the inverse of the frame mapping. SEQUENCE rows emit `contextRequested` (step rows: edit, enable, move, duplicate, remove; the Click-mode ZONE row: redraw, clear, outline). Step cards pop their own `···` menu on right-click (`_StepCard.menu`). Keep new menus in that module so wording and behaviour stay shared.
- **Monitor identity.** `target_monitor` / `ai_monitor` keep their index but `target_monitor_identity` / `ai_monitor_identity` (name, model, serial, geometry) decide which screen that means, because Qt's screen order changed between launches on the same day. `monitor_identity.resolve_target` / `resolve_ai` return `(index, status)` with status auto / virtual / ok / legacy / missing; `match_strict` has no fallback. A `missing` screen makes `target_index` return None (the deck shows auto) and `readiness.missing_monitor_message` blocks START with "Saved monitor X is not connected" until the user reselects or picks Auto. Never resolve a missing screen to another one: that is how clicks land on the wrong monitor.
- **Zone map is the monitor picker.** `ZoneMap` is a fixed 150 px well; the engine's target monitor is ice-framed and tagged TGT (explicit) or AUTO. Left-click a monitor to set `target_monitor` through `App.set_target_monitor`, right-click for the list plus Auto. That App method saves, pushes bounds to the engine, refreshes the Settings combo, the viewport and the map, and toasts. The cadence panel takes the right column's spare height instead.
- **Click card has no mini-map.** The area is drawn on the real screen and shown by the viewport and the zone map; the card keeps one summary line, DRAW / CLEAR, and the SHAPE / LOCK / ON SCREEN rows, each with a tooltip on its label and its cells (`SegmentedControl(tooltips=...)`). Controls (buttons, segments, row labels) read at `SIZE_CONTROL` 12 px with `CONTROL_TRACKING` 0.6 px, larger than the 11 px hints, because 11 px tracked uppercase was hard to read on the 100 % ultrawide.
- **Icons.** `ui/icons.py` builtins are 24-unit stroke SVGs; the header uses `monitor` (signal arcs, the LAN stream), `eye` / `eye-off` (outline toggle, swapped with `IconButton.set_icon`), `settings` (a cog, path after Lucide) and `expand` (fullscreen). `display` is a screen on a stand for monitor pickers. `DeckShell.set_view("deck"|"editor")` and `current_view()` remain as compatibility wrappers (editor = pane open).
- **Viewport resolution.** The widget sends the worker its image area in device pixels (`size * devicePixelRatioF`, re-sent on resize, zoom and DPR change) and the worker scales the native grab once to fit it, downscaling only (never above native, capped at 3840 wide), then stamps the widget's DPR on the `QImage` so `drawImage` maps device pixels 1:1. Hairlines (grid, rulers, chip borders) are cosmetic pens drawn without antialiasing; ruler labels are 9 pt DemiBold. `main.py` sets the `PassThrough` high-DPI rounding policy so a 150% monitor stays 1.5x.
- **Window geometry.** `initial_geometry(cfg)` restores `window_x / y / w / h` only when that rect still intersects a connected screen; otherwise the window opens at 80% of the available area of the screen under the cursor, centred, never below 1200 x 760. `closeEvent` saves all four (normal geometry when maximized or fullscreen).
- **Viewport pan.** While zoomed, or cropped in cover mode, a left-drag on the viewport moves the view (`Viewport.set_pan`, an offset in DIPs from the zone centre, clamped by `_pan_limits` so the view stays on the monitor; reset on a zoom change). The painter maps through the current VIEW rect (`_view`, refreshed per paint) and draws the last frame where it belongs (`_frame_draw_rect`), so the picture moves at once and the uncovered strip shows the grid until the worker's next grab. The cursor is an open hand when a drag would do something.
- **Viewport zoom.** Levels 1x / 1.5x / 2x / 3x. The `+` and `-` ends of the zoom rail, the mouse wheel over the viewport, and a double-click (toggles 1x and 2x) all drive it. Zoom shrinks the worker's target rect (`CaptureWorker.set_target_rect`) around the active zone, or the monitor centre with no zone, clamped inside the monitor, so a zoomed frame is cheaper to grab, not dearer. Rulers relabel to the visible monitor-local DIP range and are clipped to the image; the bands outside the aspect-fit image are painted in `SURFACE_PANEL` with the hairline grid. Nothing about zoom persists. A `TRK 0.87` chip under LIVE reports `clicker.tracker_confidence()` while a Track step is current: green at or above the step's `tracker_threshold`, amber below, red when the engine runs a Track step and reports nothing.
- **Control deck.** ACTIONS holds three buttons. HOLD is universal: `clicker.toggle_pause()` for Click / Record, `bot_runner.toggle_pause()` for AI, label flipping to RESUME, enabled whenever something runs; the same slot (`App._toggle_pause`) serves the F8 hotkey and the palette. TEST CLICK (`test_btn`) runs `App._test_click_once` in Click mode with a zone and says why it is off otherwise. The screen action (`capture_btn`, a text button) is DRAW ZONE / REDRAW ZONE in Click mode and CAPTURE / PICK COLOR / DRAW ZONE for the selected, else expanded, else first Track / Color / Click step in Record mode. The header STATUS chip shows `HOLD` with an amber dot while paused (`TARGET LOST` still wins while the engine holds on a lost window), and paused counts as running for the WidgetLocker. L / R / M write `click_type`, middle included. The nudge pad moves the Click zone, or in Record mode the running (else first) Click step's zone through the debounced step save; the `1 PX` label is a button cycling 1 / 5 / 20 px.
- **Right column** (quiet while idle, September 2026): ZONE MAP first, then ENGINE STATUS and TIMING & TARGETING, both `Panel(collapsible=True)` and folded to their title rows until the engine runs (`sync_open(running)`; a click on the title opens one by hand), then CURRENT RUN (`CurrentRunPanel`, aliases `MissionPanel` / `RunProgressPanel`), which is hidden while idle. The setup checklist lives in the left panel (titled CHECKLIST in Click, SEQUENCE in Record, BOT in AI): Click rows are numbered 01 DRAW ZONE / 02 WAIT / 03 TEST ONE CLICK, then an OPTIONS caption (LIVE while running) over BREAKS, STOP AFTER and key timers; there is no ENGINE row (the STATUS chip carries state); `RowSpec(divider=True)` paints a caption; `SequencePanel.footer` is the one sentence on the deck that says what blocks START. ENGINE STATUS (every row has a tooltip via `KVGrid(tips=...)`; the HID row reads READY in green or a short fault such as `COM8 NOT OPEN` in red from `_hid_summary`, with the backend's full message and the probe age in the tooltip; click re-probes `key_backend_status()`; MONITOR row shows the LAN host:port from `monitor_server.lan_url()` while streaming and opens the Monitor page on click; FATIGUE reads `bot_runner.fatigue_multiplier()` in AI mode), ZONE MAP (`zone_map.py`, a tactical plot: bracketed corners, all monitors as outlines with the target ice-framed, the zone marker with its anti-cluster ring, recent clicks as contacts fading over 45 s, and a green **sweep** that turns around the zone only while the engine runs, driven by a 30 fps `QTimer` the column tick starts and stops through `sync_sweep()`; the footer reads CORNER STOP, reports `clicker.corner_abort_armed()` and toggles `corner_abort_enabled` on click), TIMING & TARGETING (WAIT range via `common.fmt_secs`, CURVE from `clicker.delay_curve()`, anti-cluster indicator, the interval strip which reads NO CLICKS YET until there is data), and CURRENT RUN (PROGRESS / CLICKS / RECOVERIES, running only). `App._checklist_tested` ticks the SEQUENCE panel's TEST row after a test click. Bot slugs are shown as manifest names through `common.bot_display_name`.
- **Session chip.** `PC-MMDD-HHMM`, minted on every engine START (`App._begin_session`), with `T+HH:MM:SS` appended while running from `session_uptime_seconds` (bot runs use the START timestamp).
- **Settings drawer** (`settings_drawer.py`): a non-modal tool dialog holding the config pages (Hover, Behavior, Hotkeys, Timers, Stats, Monitor, Settings, Help). Opened from the header gear, the monitor button, Ctrl+4 / Ctrl+5 and the palette nav commands.

Compatibility: `app.nav_rail` is a `NavShim` on the deck, `app.pill` is a hidden StatusPill whose `tick()` still runs, and `App.show_page(id)` routes to a mode (opening the editor pane) or a drawer page on either shell. The capture worker keeps running while the editor pane is open; it stops when the window hides, when the splitter collapses the viewport to zero width, and in `closeEvent`.

Icons come from `ui/icons.py` (built-in stroke SVGs plus six Fox Rockett micrographics under `ui/assets/micro/`, recoloured at load). Fonts (JetBrains Mono, Barlow) ship in `ui/fonts/` and load in `main.py` before the App is built.

### Classic shell

Wide-format PySide6 window, default 1280 × 800 (min 960 × 600), resizable. Three persistent chrome elements wrap one swappable page surface:

- **NavRail** (left, fixed-width): vertical icon+label list, one entry per page (Click, Record, AI, Hover, Behavior, Hotkeys, Timers, Stats, Monitor, Settings, Help). Active item shows an ice left-edge stripe.
- **TopBar** (top, 52 px): `BRAND   ◉ status pill   [▶ START] [■ STOP]   Esc to abort   ⌘K   👁 ON/OFF`. Status pill, START/STOP, and Esc hint cluster on the right (the spare horizontal space sits between brand and pill).
- **Page stack** (center): one page per nav item; switching the rail just swaps the central widget.

### Two parallel UI patterns
The pages split cleanly into two visual languages, see *"When to use which pattern"* below. Mode pages (Click / Record / AI) use **Card → Section → Field → action row**; config pages (everything else) use the flatter **GroupHeader → SettingsGroup → SettingsRow** rhythm.

### Tracker preview overlay
While idle in Record mode, the App's tracker loop runs `locate()` at the active step's `update_rate_hz` and a `QTimer` tick redraws a translucent click-through `QWidget` box following the target. Color encodes state: neutral `INFO` (preview, locked), amber (preview, searching), green `RUN` (engine running, locked). Overlay is hidden when the user removes the preview step (`_cleanup_removed_track_step`) and respects the topbar `👁 ON/OFF` master toggle.

### Scrolling
Page contents that overflow live inside a `QScrollArea` per page; each is independent, so wheel events naturally route to whichever scrollable the cursor is over. No custom router needed (the Tk `_smooth_scroll_router` glue is gone with the CTk migration).

---

## Humanization (`utils/humanizer.py` + `fatigue.py` + `idle_wanderer.py`)

All controlled by a single `realism` dial 0..1 in the GUI; `_apply_realism()` derives every per-feature value (frequencies, durations, intensities) so users don't need to think about Advanced unless they want to.

- **Movement**: Bezier curves with 1–2 random control points, ease-in-out velocity, ±1–2 px wobble, optional overshoot + correction.
- **Click timing**: 20–80 ms pause before the button fires; 40–120 ms gap between double-click halves.
- **Inter-click delay**: log-normal distribution centered low in the user's range, with an upper soft-clamp tail (matches real human inter-action timing studies).
- **Fatigue**: gradual multiplier on movement / delay times that grows with wall-clock session time (`intensity` per hour, capped at 1.5x `intensity`), plus scheduled "break bursts": multi-second sleeps every 40–70 clicks (configurable).
- **Idle wander**: cursor occasionally drifts to a random point in (or near) the zone *between* clicks.
- **Hover zones**: rare visits to other on-screen regions where the cursor dwells without clicking.
- **Distraction spike**: occasional 3–12 s "looked away" pause every 60–180 clicks at high realism.
- **Muscle memory**: first click of a session is ~20 % slower than typical; movement duration decays exponentially toward floor by ~click 10.
- **Anti-cluster**: targets are repelled from the last 10 click points so distribution doesn't cluster on a Gaussian peak.
- **Micro-jitter tick**: between waits, occasional 1-px nudges to mimic mouse-sensor noise (a frozen cursor is a strong tell).
- **Post-click micro-wander**: 5–30 px curved drift right after every click.

---

## Hotkeys (`modules/hotkey_manager.py`)

Global hotkeys captured by a `pynput.keyboard.Listener` running in its own thread. Defaults: **F6** = Start, **F7** = Stop, **F8** = hold/resume (the click engine or a bot, whichever runs), **F9** = capture; **Esc** is the hard-coded emergency stop. Start, Stop and Pause are rebindable from the Hotkey card; the rebind UI captures the next keypress (Escape cancels, can't bind to another action's key, can't be empty). Persisted as `hotkey_start` / `hotkey_stop` / `hotkey_pause` in `config.json`. The Help page and the Ctrl+K palette read these keys from config rather than hardcoding them. Palette navigation: Ctrl+1 Click, Ctrl+2 Record, Ctrl+3 AI, Ctrl+4 Monitor, Ctrl+5 Settings; Ctrl+E toggles the deck's side pane, Ctrl+H the on-screen outlines.

**Never log raw keystrokes.** The listener sees every keypress on the machine, so it may log only bound-key matches; during a rebind capture it logs that a key was captured, never which one. `capture_next` holds one pending capture: a second call while one is pending replaces it and writes a warning. `start()` restarts the listener if its thread has died.

The corner-emergency-stop watchdog spins separately: any time the cursor lands in a screen corner (within 2 px), the engine stops immediately. `corner_abort_enabled` (default true) switches it off; the deck's zone-map footer toggles the key and pushes it to the engine.

---

## Key Timers (`modules/key_timer.py`)

Passive concurrent keypresses for things like potion macros: *"press Z every 6 minutes while my farming sequence runs."* They are **not** steps, they don't advance recorder state, don't move the cursor, and aren't gated by the active step. Each `KeyTimer` is `{key, interval_min, interval_max, enabled}`. Combo strings are `+`-joined (`"z"`, `"f1"`, `"ctrl+z"`, `"ctrl+shift+f5"`); `parse_combo` validates them and resolves modifiers via `pynput.keyboard.Key`.

When `Clicker.start()` succeeds, it spawns one daemon thread per enabled+valid timer running `run_timer_loop`, which sleeps `random.uniform(interval_min, interval_max)` between fires using the engine's shared `_stop` event. On `stop()` (or any natural exit of `_run`) `_stop.set()` reaps every timer cleanly. Timers fire only while the engine is otherwise running, they don't keep the engine alive on their own. Persisted as `key_timers` in `config.json`.

---

## Configuration

`config.json` lives next to the running script / exe. `load_config()` merges the file over `DEFAULTS` and runs auto-migrations (legacy `hotkey_toggle` → split keys, single `hover_zone` → `hover_zones` list, palette refresh). `RecorderStep.from_json` separately migrates legacy `is_pause` → `kind`. A corrupt file is renamed to `config.json.bak.<timestamp>` and defaults are used.

Selected keys:

```jsonc
{
  "hotkey_start": "f6",
  "hotkey_stop": "f7",
  "hotkey_pause": "f8",
  "min_delay": 5.0,
  "max_delay": 20.0,
  "click_type": "left",
  "click_mode": "single",
  "realism": 0.5,
  "zone": { "shape": "rect", "rect": [...], "circle": null, "vertices": [] },
  "active_mode": "clicker",            // "clicker" | "recorder" | "ai"
  "recorder_steps": [ { "kind": "click"|"track"|"color"|"key"|"pause"|"loop", ... } ],
  "recorder_expanded_steps": ["<step_id>", ...],   // which step cards are expanded in the UI
  "hover_zones": [ ... ],
  "key_timers": [ { "key": "z", "interval_min": 360.0, "interval_max": 360.0, "enabled": true } ],
  "corner_abort_enabled": true,        // corner watchdog; the deck's zone-map footer toggles it
  "key_input_method": "auto",          // "auto" | "sendinput" | "interception" | "serial_hid"
  "serial_hid_port": "COM3",
  "ai_bot_slug": "menaphos_acadia",
  "ai_tick_rate_hz": 5.0,
  "ai_monitor": 1,
  "ai_dry_run": true,
  "ai_wiki_fetch_enabled": false,     // outbound runescape.wiki lookups; off by default
  "ai_author_tools": false,            // AI pane: show captures / library / rules / calibration / log
  "show_zone_overlay": true,
  "monitor_token": "...",                // set on first Monitor enable
  "monitor_port": 8765,
  "window_x": null,                    // deck shell: restored only if the rect still hits a screen
  "window_y": null,
  "window_w": 1280,
  "window_h": 800,
  "deck_editor_open": true,            // deck shell: editor pane shown beside the viewport
  "deck_splitter": null                // [viewport_px, pane_px]; null = 56 / 44
  // ... realism-derived per-feature toggles, intensities, durations
}
```

Saved on every meaningful change (button click, zone draw, and 200 ms after a slider settles via `ui/debounce.py`, never per drag tick). No explicit Save button.

---

## Color & Type (`ui/theme.py`)

"Command deck" theme, slate edition (September 2026). Operations-console look: charcoal-slate base (`BG #0E1116`, never pure black), blue-grey panels in `SURFACE #151A21` with a full 1 px `BORDER #26303B` and an 8 px radius, recessed wells (`SURFACE_PANEL #11161C`) for inputs. No shadows, no glow, no gradients, no scanlines, no emoji in the UI (icons come from `ui/icons.py`). Restraint is the point: the references are Lattice and TAK, not a game menu.

**Two accents, one meaning each.** `ACCENT #7CC4F2` (ice blue) is **selection and control**: the active mode row, the selected segment, a checked switch knob, a focused input border, the target monitor frame, the zone outline and reticle, the primary button (START, DRAW ZONE, ADD STEP). `RUN #4ADE80` (green) is **live and nominal**: the RUNNING status, the running step's stripe and dot, a firing rule, the NEXT countdown, the viewport brackets and zone-map sweep while the engine runs, a subsystem square that reports healthy, the Monitor card's listening stripe. Neither is decoration and neither is a heading colour. Section eyebrows and group headers are `TEXT_TERTIARY`. Red (`STOP / DANGER #E5484D`) is stop and fault. Amber (`WARN #E0A83A`) is caution. `INFO #8C9AA8` is neutral. A green START on an idle engine would say nothing, which is why START is ice and STATUS turns green.

**Type is split by job.** Barlow (`FONT_FAMILY`, bundled in `ui/fonts/`) carries every label, button, heading and sentence; JetBrains Mono (`FONT_MONO`) carries values, coordinates, times, keys, inputs and the log. `main.apply_app_font` installs Barlow as the application font at `SIZE_BODY` px, weight `FONT_WEIGHT_BODY` (500) with `PreferFullHinting`; full hinting is what keeps 12 to 13 px text sharp on a 100 % monitor (the user's ultrawide). **The stylesheet sets no font on the universal `QWidget` or bare `QLabel` selector.** A stylesheet font beats `QWidget.setFont` on every widget it matches, and the old universal rule silently flattened the wordmark, the mode names and every deck label to 13 px mono; roles (`card-header`, `section-label`, `mono`, `stat-value`, `QPushButton`, ...) set family, size and weight where a role needs them, and painted or `setFont` text keeps what it asked for. Barlow Bold is the wordmark (`FONT_DISPLAY`, `SIZE_TITLE` 22). Scale, whole pixels only because Qt's stylesheet parser drops a fractional `font-size`: 11 (ruler ticks, `TEXT_MICRO`), 13 (uppercase labels with `LABEL_TRACKING` 1.2 px, hints, panel headers), 14 (body, buttons at `SIZE_CONTROL` with `CONTROL_TRACKING` 0.8 px), 15, 19; the wordmark is 24. This is one step up from the first slate pass: the final review (Runway and by eye at 2x) found 12 to 13 px small on the ultrawide. Deck captions (`SIZE_CAPTION` = `SIZE_XS` - 1) sit one step under the row text so the value is the loudest thing on a line. The deck's own painted labels (`deck/common.py` `label_font` / `micro_font` for Barlow, `mono_font` for values) run 4/3 of those sizes in pixels, the old point sizes, with the same hinting. Panel headers are uppercase 12 px Barlow, 600 weight, 1.6 px tracking. QSS cannot uppercase or track text, so widgets uppercase their strings and set `QFont.setLetterSpacing` themselves.

**Tactical marks that earn their place.** Corner brackets (`zone_map._brackets`) on the live viewport and the zone map. The zone-map sweep while running. The DTG clock and SESSION id. The subsystem strip. The trust band. Nothing else moves or glows.

**Radii and sizes.** `RADIUS_CARD` 8, `RADIUS_BUTTON` / `RADIUS_INPUT` / `RADIUS_PILL` 6. No full-round pills anywhere. Controls are 30 px tall (`INPUT_H`, `BUTTON_H`), hero START/STOP 32, icon buttons 30 x 30. Toggles are a 30 x 14 rectangular switch with a 12 x 10 square knob. Sliders: 1 px `BORDER_STRONG` track, 3 px ice fill, 10 px round knob, optional `TickRuler` beneath (`show_ruler=True` default).

**Motion.** State changes are instant. `DUR_NORMAL` 120 ms linear is the ceiling and only the Expander uses it. The one exception is the zone-map sweep (`SWEEP_PERIOD_MS` 4000, 30 fps `QTimer`), which turns only while the engine runs and stops the moment it stops: motion is allowed where it reports live state and nowhere else.

Every pre-deck token name (`START_HOVER`, `STOP_QUIET`, `ACCENT_TINT_*`, `GROUP_*`, `ROW_*`, size aliases) is kept as an alias in `ui/theme.py` so older cards keep importing. `STATUS_ACTIVE` now equals `RUN`.

---

## When to use which pattern

PhantomClick uses two parallel UI patterns. Pick one when adding a new tab; do not mix them within a single page.

**CARD-BASED (mode pages):**
- Click, Record, AI
- Use Card → Section → Field → action row
- Components: `Card`, `SectionLabel` (or `Section` for richer headers), `Expander`, step-card stripe (2 px ice left edge when expanded, green when the engine is on it)

**FORM-ROW (config pages):**
- Hover, Behavior, Hotkeys, Timers, Stats, Settings, Help
- Use `GroupHeader` → `SettingsGroup` → `SettingsRow`
- Tighter rhythm, flatter hierarchy, no cards

**HYBRID:**
- Monitor: wraps a `Card` (for the listening-state stripe and a header `StatePill`) but every internal row is canonical `SettingsGroup` + `SettingsRow`. The Card chrome is justified by the active-state visual signal that doesn't fit a flat form-row page. Documented hybrid; do not extend the pattern further unless a similar live-state need appears.

When adding a new tab, classify it as **"mode"** (an active workflow that has live state, running engine, live preview, log output, current step) vs. **"config"** (set-and-forget settings the user adjusts then forgets about). Use the corresponding pattern. Do not mix the two within one page, the visual languages don't compose cleanly.

## Design system patterns

### Active-state stripe: 2 px `[active="true"]` (or `[expanded="true"]` / `[listening="true"]`)

A 2 px left edge on a container marks state. Ice means selected, green means live:
- Nav rail items (active page): ice
- Step cards in Record: `[expanded="true"]` ice (selected), `[active="true"]` green (the engine is on this step)
- Monitor card (`[listening="true"]`) when the streaming server is running: green
- Behavior master groups (`[active="true"]` on `SettingsGroup`) when the master switch is on: ice

Implementation: a per-attribute QSS rule (`QFrame#card[listening="true"]`, `QFrame[role="settings-group"][active="true"]`, etc.) plus a tiny `set_active(bool)` / `_set_listening(bool)` helper on the widget that sets the property and re-polishes. **Reuse the existing pattern**; don't invent a parallel mechanism.

### Warn-outline buttons: `variant="warn-outline"`

Amber border + amber text for actions whose side effect is destructive enough to deserve a visual cue but common enough that a confirm dialog would be friction (Monitor's "Regenerate token", invalidates existing phone URLs). **Always pair with a tooltip** that explains the consequence in plain language. If the action is rare AND irreversible, prefer a `QMessageBox` confirm dialog instead.

### Disclosure widgets: `Expander` only

The `Expander` widget owns its own chevron via an internal `_ExpanderToggle` row. **Never bake `▸` or `▾` into the label string**: it renders a duplicate chevron. Pass the label only:

```python
self.expander = Expander("Advanced, watchdogs & auto-camera")  # correct
self.expander = Expander("▸  Advanced, watchdogs & auto-camera")  # WRONG, double chevron
```

Action buttons (Test step, Add view, etc.) **never** use a `▸` prefix: it reads as a disclosure affordance and confuses the click target. The button shape itself is the affordance.

### Format helpers: display vs. edit

`ui/format.py` is the single source of truth for **display** formatting: `fmt_count`, `fmt_delay`, `fmt_position`, `fmt_rate`. `ui/screen_utils.py` owns `screen_label` for monitor enumeration. Before adding a new f-string in a card, **check these modules first**.

**Important principle: canonical formatters apply to display surfaces, not edit surfaces.**
- Display surfaces (chips, badges, readouts, status pills): use the canonical helper. They show *settled* values where consistency matters.
- Edit surfaces (spinboxes, sliders, text inputs): respect the user's chosen unit and precision. A timer set to "every 15 min" should edit in minutes, not in `fmt_delay`'s 3-decimal seconds. Forcing a canonical format on an edit field destroys the user's mental model of the value they're tuning.

### Section labels and group headers

Section eyebrow labels (Click / Record / AI internal cards) and group headers (form-row pages) both render in **`TEXT_TERTIARY` Barlow at 12 px uppercase, tracked**. Never an accent. Drop trailing hairline rules, the tracked uppercase carries the section marker by itself; half-rendered rules read as bugs.

## Sprint history

The 2026 design pass shipped in six focused sprints:

- **Sprint 1: Token polish.** Group headers and section labels routed to `t.ACCENT`. `stat-value` font tokenized to `t.SIZE_STAT_VALUE` with explicit `QFont` lock (QSS attribute selectors lose to inherited fonts). Help page key labels demoted from `t.ACCENT` → `t.ACCENT_TEXT`. Click divider annotated as intentional rhythm whitespace.

- **Sprint 2: Format utilities.** Extracted `screen_label()` to `ui/screen_utils.py` (Monitor and Settings had diverged copies, the Monitor copy never normalized 3-letter EDID codes like `"AUS"` → `"ASUS"`). Added `fmt_count`, `fmt_position`, `fmt_rate` to `ui/format.py`. Stats tab values normalized to canonical formatters (3-decimal delays, `CPM` suffix, locale comma). 27 unit tests in `tests/test_format.py`.

- **Sprint 3: AI tab consistency.** Replaced the Hero card's custom `QPushButton` setup-notes toggle with the canonical `Expander` widget (gains 220 ms `OutCubic` slide animation). Tokenized hardcoded `4 px` spacing to `t.SP_XS`. Switched bot dropdown selection-bg from `ACCENT_DIM_FALLBACK` (solid hex) to `ACCENT_DIM` (rgba) for visual consistency. **Found and fixed a double-chevron bug** in the Config-section Expander (label was being constructed as `"▸  Advanced, …"` while `_ExpanderToggle` already renders its own chevron).

- **Sprint 4: Monitor card refactor.** Migrated from ~180 lines of handcrafted `QHBoxLayout` rows to declarative `SettingsGroup`/`SettingsRow`. Extended `SettingsRow` with `mono_desc=False` kwarg (renders desc as mono primary instead of quiet tertiary, used by the Phone URL row). Added `[listening="true"]` active stripe pattern. Added `variant="warn-outline"` button variant for the Regenerate-token action. Replaced explicit `QFrame divider` with `addSpacing`.

- **Sprint 5: Timers polish.** `TimerRow` was already honoring the `SettingsRow` contract via `role="settings-row"` + `set_last()` + `SettingsGroup` integration; the audit had pattern-matched on widget names and missed the actual contract compliance. Minimal three-edit fix: canonical `t.ROW_PAD_Y` (was `-2`), tokenized the 36 px row-2 indent into `_BADGE_W + t.SP_SM`, mono font on the interval spinbox.

- **Sprint 6: Final polish.** Behavior master groups now light up the `[active="true"]` left stripe on their `SettingsGroup` when the master switch is on (Stop-after's two masters OR-aggregate). Added `SettingsGroup.set_active(bool)` and the matching QSS rule, mirroring Sprint 4's MonitorCard pattern. Documented all of the above in this file.

### Audit retrospective

The audit's TimerRow finding ("MEDIUM, structural refactor") was based on a pattern-matched read of the widget name and two-line layout. The actual implementation already honored the `SettingsRow` contract (role attribute, last-row management, `SettingsGroup.add_row` integration). **Lesson:** audit findings are hypotheses; verify against the implementation before sizing the fix. A widget that doesn't subclass `SettingsRow` can still satisfy its visual contract, and a widget that does subclass it can still violate the visual contract. Subclass relationships are weaker than role/QSS contracts in this codebase.

## Process for new tabs or major UI changes

1. Classify the surface as **mode** / **config** / **hybrid** (and justify hybrid).
2. Use the corresponding pattern stack (Card or GroupHeader/SettingsGroup).
3. Read `ui/format.py` and `ui/screen_utils.py` before inventing local formatters.
4. Read this section and confirm proposed changes don't violate established patterns. If a new pattern is needed, propose it as an addition here **before** implementing.

---

## Critical Rules

1. **Mouse must physically move.** No coordinate-only clicks; the cursor visibly travels.
2. **All movement looks human.** Bezier, speed variation, jitter, overshoot. Never a straight line at constant speed.
3. **Hotkeys work globally**: even when a fullscreen game has focus.
4. **Stop is instant.** Every wait goes through `Event.wait()`; no `time.sleep()` in the engine.
5. **GUI never freezes.** Engine, watchdog, tracker, hotkeys all run on background threads.
6. **No outbound network.** No telemetry, no updates, no analytics. The opt-in Monitor tab serves screen + status to the user's own devices on the local network, but only when the user explicitly enables it; that's the single carve-out.
7. **Zone overlays are click-through**: they never intercept the actual game's clicks. The outline is always the theme accent (`theme.ZONE_DEFAULT_COLOR`, ice blue); `zone_color` is a dead config key and is dropped on load. Only `zone_opacity` and `show_zone_overlay` are settings, toggled from the header eye button, the Click editor's ON SCREEN switch or the palette, all through `App.set_overlay_visible`.
8. **Config persists between sessions** via local JSON.
9. **Track templates are per-step**, keyed by `step.step_id`, stored in `templates/`.
10. **Multi-monitor aware where it matters.** Click / Track / Color modes capture from `monitors[0]` (the virtual screen union), so a zone drawn on a secondary monitor is captured correctly. AI mode pins to a single monitor index (`ai_monitor`) since the bot's coordinate logic assumes one frame.
11. **Never log raw keystrokes.** The hotkey listener may log only bound-key matches. Anything that writes key names to `phantomclick.log` for unbound keys is a keylogger and must not ship.

---

## Build & Package

```powershell
py -3.11 -m pip install -r requirements.txt          # dev run
py -3.11 main.py

pwsh -File build.ps1                                  # single-exe build
```

`build.ps1` locates a Python 3.11 (`py -3.11`, then a PATH `python` that reports 3.11), installs `requirements.txt` + `requirements-build.txt` (skip with `-SkipInstall`), warns if `serial` or `interception` are not importable (the exe would silently lack those backends), then runs `pyinstaller PhantomClick.spec --noconfirm --clean`. The spec is the source of truth; what it does:

- `datas`: `ai/tasks/library` (every `*.task.yaml` + companion `.py`, loaded by file path at runtime so static analysis never sees them), `rs3vision` (package source + `templates/*.toml`), `packaging/phantomclick.ico`, and `packaging/boot` (the boot animation frames).
- `binaries`: `rs3vision/_rs3vision.pyd` (Python 3.11 only; see `rs3vision/README.md`).
- `hiddenimports`: `collect_submodules("ai")` + `collect_submodules("pynput")`.
- `Splash("packaging/splash.png")` shown while the onefile unpacks; dismissed from `ui/app.py` via `pyi_splash`.
- `icon="packaging/phantomclick.ico"`, `console=False`. `assets/` is gitignored and not part of the build.

Output: `dist\PhantomClick.exe`.

**Mark, icon, splash and boot animation (Blender, September 2026).** The app mark is a 3D "phantom cursor": an ice-glass arrow with a fading ghost trail locking into corner brackets over a slate plate, in the theme palette. `packaging/blender_mark.py` builds the scene and renders it headless (`"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b -P packaging/blender_mark.py -- --still --anim`, `--quick` for half size) into `packaging/render/` (gitignored): `mark_1024.png` (icon variant, bigger cursor) and 48 square frames of the cursor sweeping in and the brackets locking. `packaging/make_icon.py` turns the still into `phantomclick.ico`; `packaging/make_boot.py` composes `splash.png` (960 x 480, the PyInstaller unpack splash, 2x so Windows downscales it on a scaled monitor instead of stretching) and `packaging/boot/frame_NN.png` (48 frames, 1440 x 720, from the first 48 of the 1080 px video renders: mark left, Barlow wordmark right, tagline and the LOCAL · OFFLINE line fading in). `ui/boot_splash.py` plays those frames at 30 fps in a 720 x 360 logical frameless window centred on the cursor's screen while `App` is built; each pixmap carries `FRAME_SCALE` 2.0 as its device pixel ratio so the picture stays sharp at 100 %, 150 % and 200 %, then `run()` shows the window; a click or key skips it, `boot_animation: false` in config or `PHANTOMCLICK_NO_BOOT=1` disables it, and a missing frames folder means it never shows. The composed PNGs and the .ico are committed, so a build never needs Blender. This is the one place motion is decoration: it runs before the console exists and never again. `--hero` and `--video` render the README hero still (2160 square) and a 96-frame release sequence with a click ring; `packaging/make_media.py` composes them into `docs/media/hero.png` / `hero.webp` (the README header) and `docs/media/boot.mp4` / `boot.gif` (release page and README) with ffmpeg.

## Known gaps

- **Two step vocabularies.** The AI tab's step DSL (`ai/bot/compiler.py`, persisted as `ai_user_bot_steps`) defines its own kinds (`KIND_ZONE_CLICK`, `KIND_KEY_PRESS`, `KIND_WAIT`, `KIND_LOOP_BACK`, `KIND_FIND_COLOR_CLICK`, ...) that overlap the Recorder's `RecorderStep` kinds. A decision to merge them onto one model or remove the AI DSL is pending; until then, changes to step semantics have to be made in both places.
- **rs3vision source is outside the repo** and not under version control. See `rs3vision/README.md`.
- **Config wipe of 2026-09-04 never root-caused.** During the audit tooling pass the populated `config.json` was replaced with defaults while keeping its mtime. The only writer is `save_config` (atomic) and the only defaults source is `load_config` on a missing or corrupt file, so the likely path was a test or script building the App against the real config path. Guards now: `tests/conftest.py` redirects `config_io._config_path` for every test and fails the session if the real file's hash changes; `load_config` restores from the rolling `config.json.bak` before falling back to defaults; `pytest.ini` limits collection to `tests/`.

---

## Out of Scope (intentional)

- Scripting language / external macro DSL (recorder steps + AI bot scripts cover the use cases without inventing a new language).
- Outbound network features (telemetry, auto-update, analytics, cloud sync). The Monitor tab's local LAN HTTP server is the single carve-out and is opt-in.
- Auto-update mechanism.
- Cross-platform support: Windows-only by design (Arduino HID + NXT context don't generalize).
