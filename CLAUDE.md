# PhantomClick — Human-Like Auto Clicker

## What Is This?

A Windows desktop auto-clicker built around the idea that *what looks human is human enough*. The cursor physically moves along curved paths, dwells, jitters, fatigues, and occasionally takes breaks; clicks land at randomized points inside a user-drawn area; timings are sampled from log-normal distributions instead of uniform ones. The user controls all of this from a dark, landscape PySide6 Qt window with three top-level modes:

- **Click** — pick one area on screen and the engine clicks inside it forever.
- **Record** — build an ordered sequence of steps (click / track / color / key / pause / loop) that runs top-to-bottom and loops.
- **AI** — run a rule-based RuneScape bot from `ai/tasks/library/`. Bot rules dispatch through PhantomClick's humanizer for clicks and the Arduino HID backend for keystrokes (the only NXT-resistant keyboard path).

Everything runs locally — no network, no telemetry, no auto-update.

---

## Phase 2 Hardware Roadmap (long-term)

A pro-grade RS3 bot stack is on the roadmap, all hardware on hand: **Captain DMA Fuser** (Main PC PCIe, reads RAM directly — invisible to NXT), **Elgato PCIe capture card** (Bot PC, HDMI passthrough — Main PC sees only a monitor), and **KMBox NET** (USB to Main PC for HID, Ethernet to LAN for commands — looks like a real mouse + keyboard).

The bot will live entirely on a separate Bot PC. Main PC will see: a monitor, a HID device, and a generic PCIe card. No software touches RS3.

Phase 2 is a hobby-pace multi-month build, gated on Phase 1 (color detection recovery) completing first. Phase 3 is RS3 NXT offset reverse engineering, gated on Phase 2 hardware being end-to-end verified. See **`gameplan.md`** for the full roadmap and **`docs/wiring_diagram.md`** for hardware topology.

When making architectural changes, check that they don't conflict with the planned Bot-PC-side mode: anything that hardcodes "engine runs on the same machine as the game" or "mss is the only frame source" will need rework in Phase 2.

---

## Tech Stack

- **Language:** Python 3.11 (pinned — the bundled `rs3vision/_rs3vision.pyd` Rust core is ABI-bound to 3.11)
- **GUI:** PySide6 / Qt 6.6+ (warm-neutral slate palette, teal `#22d3ee` accent, Segoe UI Variable type)
- **Mouse:** `pynput` via humanized Wind/Hooke paths today; **KMBox NET** over LAN is the planned Phase 2 input path (NXT-invisible HID controller, see `gameplan.md`).
- **Keyboard:** `modules/key_input_backend.py` — selectable backend (SendInput / Interception / Serial HID via Arduino Leonardo + PhantomHID firmware). Arduino HID is the only software path NXT does not filter; Phase 2 adds `kmbox_net` as a fourth option that handles mouse + keyboard from off-machine.
- **Screen capture / template matching:** `mss` + OpenCV (`cv2.matchTemplate`, multi-scale `TM_CCOEFF_NORMED`); AI mode also uses a Rust-backed vision library (`rs3vision`) for CTS color clustering + DTM template matching.
- **Numerics / image:** `numpy`, `Pillow`
- **AI mode:** RS3 bot framework merged in at `ai/`; Rust vision core ships at `rs3vision/`. `@bot.rule` decorator pattern, BotRunner on a QThread.
- **Packaging:** PyInstaller (single .exe)
- **Target OS:** Windows 10/11

---

## Project Layout

External documentation pointers:
- **`gameplan.md`** — durable Phase 1 / Phase 2 / Phase 3 roadmap, hardware inventory, considerations.
- **`docs/wiring_diagram.md`** — Phase 2 hardware wiring topology (Mermaid diagram + ASCII fallback + cable BOM).
- **`phantomclick.log`** — runtime log file at repo root; instrumented `[find_any_color/<label>]` lines surface color-detection diagnostics.

```
AutoClicker/
├── main.py                  # Entry point (DPI-aware, spawns App)
├── app.py                   # Main window — NavRail + TopBar + page stack, hotkeys, engine glue
├── config.json              # Persisted user settings (created on first save)
├── gameplan.md              # Long-term roadmap (Phase 1/2/3) — see above
├── docs/                    # Project docs (wiring diagrams, hardware setup)
├── templates/               # Per-step Track templates (`<step_id>.png` + `<step_id>_view_<uuid>.png`)
├── assets/                  # Icons, logo
├── ui/                      # Qt UI layer
│   ├── theme.py             #   Colors, fonts, spacing tokens (teal accent palette)
│   ├── topbar.py            #   Pinned top bar — brand, status pill, START/STOP, Esc hint, ⌘K, overlay
│   ├── widgets/             #   Reusable widgets — NavRail, Card, Section, Field, Expander,
│   │                        #     StatusPill, RangeSpinSlider, GroupHeader/SettingsGroup/SettingsRow
│   ├── pages/               #   One page per nav item (Click, Record, AI, Hover, Behavior,
│   │                        #     Hotkeys, Timers, Stats, Monitor, Settings, Help)
│   ├── cards/               #   Page-internal sections (steps.py for the Record body, ai.py for AI, …)
│   ├── config_io.py         #   load_config / save_config + auto-migrations
│   └── monitor_server.py    #   stdlib HTTP + MJPEG server backing the Monitor tab
├── modules/
│   ├── clicker.py           # Click engine (threading, randomization, mode dispatch,
│   │                        #   tracker integration, fatigue, watchdog, recheck-before-click)
│   ├── recorder.py          # RecorderStep dataclass + KIND_CLICK / KIND_TRACK / KIND_COLOR /
│   │                        #   KIND_KEY / KIND_PAUSE / KIND_LOOP + JSON (de)serialization
│   ├── tracker.py           # TemplateTracker (multi-scale matchTemplate, thread-safe state)
│   ├── zone_selector.py     # Zone dataclass (rect / circle / polygon) + ZoneDrawer overlay
│   ├── hotkey_manager.py    # Global Start / Stop hotkey listener (separate keys)
│   ├── color_picker.py      # Frozen-screen eyedropper overlay (returns RGB + screen XY)
│   ├── key_timer.py         # KeyTimer dataclass + combo parser + run_timer_loop()
│   ├── key_input_backend.py # Pluggable keystroke sender (SendInput / Interception / Serial HID)
│   └── stats.py             # Per-session counters (total, cpm, last pos, elapsed)
├── utils/
│   ├── humanizer.py         # Bezier + Wind/Hooke move, click timing, drift, overshoot
│   ├── fatigue.py           # Multiplier + scheduled "break burst" sleeps
│   ├── idle_wanderer.py     # Cursor wander between clicks (in-zone or whole-screen)
│   ├── window_finder.py     # ctypes EnumWindows + WM_CLOSE (Monitor "Close RS")
│   └── logger.py            # File logger (phantomclick.log next to the exe)
├── ai/                      # RS3 bot framework (merged from RS3_AI)
│   ├── bot/                 #   @bot.rule decorator, BotRunner QThread, dispatch loop
│   ├── tasks/library/       #   Bundled bots (`*.task.yaml` + companion `.py`)
│   ├── graph/               #   World-graph navigation (lodestones, edges, pathfinder)
│   ├── algorithms/          #   Shared scanning helpers (CTS, DTM, OCR, minimap)
│   ├── input/               #   InputBackend Protocol + ClickerActuatorBackend bridge
│   └── wiki/                #   Cached lookups for item / monster metadata
├── rs3vision/               # Rust vision core
│   └── _rs3vision.pyd       #   Prebuilt CTS + DTM matcher (ABI-bound to Python 3.11)
└── arduino/                 # PhantomHID firmware sketch for Leonardo (NXT-resistant keystrokes)
```

---

## Modes

### Click (single-zone)
The simplest mode and the one to use when one button keeps appearing in the same place. The user draws a rectangle / circle / polygon zone, picks a min and max delay range, and the engine clicks forever inside that zone with realism behaviors layered on top. Persisted as `zone` + `min_delay` / `max_delay` in `config.json`.

### Record (sequenced)
An ordered list of `RecorderStep`s that fire top-to-bottom then loop. Six step kinds, all live in the same list:

| Kind | What it does | Required data |
|---|---|---|
| `KIND_CLICK` | Click in a fixed zone N times before advancing | `zone` |
| `KIND_TRACK` | Follow a captured-template target (with optional alternate views for rotation / camera-angle changes) and click on it as it moves | `template_path` + `capture_rect`; optional `extra_template_paths` / `extra_template_sizes` |
| `KIND_COLOR` | Eyedropper picks a target color from a frozen-screen overlay; the engine clicks any pixel within `color_tolerance` of that color (RGB euclidean) wherever it appears. Multiple colors per step are supported via `color_extra_rgbs` — any pixel matching ANY accepted color counts as a match (useful for buttons with gradients / anti-aliased edges). An optional `step.zone` (rect / circle / polygon, drawn from the body's "Set click area" button) restricts where the engine looks for matches — critical when the same color appears on the HUD as well as the clickable target | `color_target_rgb` (+ `color_tolerance`, default 30; `color_search_rect` bounds the per-cycle scan to the picked monitor; optional `color_extra_rgbs` list for multi-color matching; optional `zone` for click-area scoping) |
| `KIND_KEY` | Sends a keystroke / combo (`f1`, `ctrl+shift+z`, …) through the configured `key_input_backend`. No cursor movement, no click. Use for hotbar abilities or chatbox commands inline with the sequence | `key_combo` |
| `KIND_PAUSE` | Wait `delay_min`–`delay_max` seconds, no click; cursor still drifts | nothing (uses `delay_*`) |
| `KIND_LOOP` | Jumps execution back to an earlier step (forever, or N more times before continuing) | `loop_target_step_id` (+ `loop_count`, 0 = forever) |

Color steps default to scanning only the monitor where the color was picked, so multi-monitor setups don't pay for the full virtual desktop on every cycle; legacy steps without a `color_search_rect` fall back to the full virtual screen.

By default the engine wraps from end-of-list to step 0 (modular `_step_idx` advance), so a sequence with only Click / Track / Pause steps loops the whole list forever. A `KIND_LOOP` step lets the user instead split the sequence into a **setup phase** (steps before the loop, fired once) and a **repeating phase** (the section between the loop's target and the loop itself, fired forever or `loop_count` more times). The recorder tab surfaces the wrap behavior in a footer line under the steps list (*"↻ After step N, loops back to step 1 forever"*) so it's never invisible.

Steps are stored as `recorder_steps` in `config.json` via `RecorderStep.to_json` / `from_json` (which also handles legacy `is_pause: bool` migration → `kind: str`).

Track-step templates live as PNGs at `templates/<step_id>.png` (relative path stored in `step.template_path`). Duplicating a track step regenerates its `step_id` so a later "Recapture" doesn't overwrite the original's PNG. Removing a track step deletes its primary PNG plus every extra-view PNG that no other step still references.

**Alternate views**: a track step can hold any number of extra captures of the same target via the row's "+ Add view" button (stored at `templates/<step_id>_view_<uuid>.png`). The engine matches the primary plus every extra against the screen each frame and uses whichever scores highest — the click box is sized by the *winning* view's dimensions, not the primary's, so a side-view match isn't misshaped by front-view geometry. This handles 3D NPCs / camera rotation / pose changes that a single template can't.

`mss` capture uses `monitors[0]` (the virtual screen union) rather than `monitors[1]` (primary only) so the capture bytes always cover wherever the user drew the box on a multi-monitor setup.

### AI (rule-based bots)
The third top-level mode. The user picks a bot from `ai/tasks/library/` (each bot is a `*.task.yaml` manifest + companion `.py` script with `@bot.rule`-decorated handlers), then START runs the bot tick loop on a `BotRunner` QThread.

Per tick, `BotRunner` evaluates every registered rule in priority order. A rule is a function `(world: WorldState) -> RuleAction | None`; the first non-None action wins, gets dispatched through the configured `InputBackend`, and the loop sleeps until the next tick.

**Vision.** Bots use the `rs3vision` Rust core (CTS color clustering + DTM template matching) for fast on-screen detection, plus `algorithms/` helpers for OCR, minimap reads, and inventory scans.

**Input bridge.** `ai/input/clicker_actuator.py` (`ClickerActuatorBackend`) implements the framework's `InputBackend` Protocol on top of PhantomClick's primitives: clicks go through `humanizer.move + click` (so they look human and respect realism), keystrokes go through `modules/key_input_backend.py` (so AI bots get the same NXT-resistant Arduino HID path that recorder KEY steps use).

**Why merged.** RS3_AI had its own placeholder humanizer and no NXT-safe keyboard path. PhantomClick already had both. Merging meant the bot framework inherits PhantomClick's realism + Arduino HID for free, and PhantomClick gains the rule-based bot mode as a peer to Click and Record.

Persisted as `ai_bot_slug`, `ai_tick_rate_hz`, `ai_monitor`, `ai_dry_run` in `config.json`.

---

## Monitor (LAN screen + remote control from phone)

A separate **Monitor** tab opt-in by the user. Two stages, both off by default:

1. **Enable streaming** — spins up a stdlib `ThreadingHTTPServer` on `0.0.0.0:<monitor_port>` (default 8765). A background thread captures `monitors[0]` at the configured FPS, resizes ≤1280px wide, JPEG-encodes via Pillow at quality 65, and caches the bytes. Endpoints:
   - `GET /` — embedded HTML page (live `<img>` of `/stream`, status panel polling `/status`, control buttons gated on the remote-control toggle).
   - `GET /stream` — `multipart/x-mixed-replace` MJPEG.
   - `GET /snapshot.jpg` — single JPEG (lower-bandwidth alternative).
   - `GET /status` — JSON: state, phase, phase_label, phase_remaining, stats snapshot, remote_control flag.

2. **Allow remote control** — additionally permits `POST /control/start`, `POST /control/stop`, and `POST /control/close-window` (which sends `WM_CLOSE` to any visible top-level window whose title contains "RuneScape", via `utils/window_finder.py`). The close endpoint also requires `confirm=true` in the form body so an accidental tap can't kick the user out of the game. WM_CLOSE is a window-level message and isn't filtered by NXT (which filters keyboard injection only).

**Auth.** Random URL token (`secrets.token_urlsafe(24)`), persisted in `config.json` as `monitor_token`. Generated on first enable. All endpoints check `?token=<value>` (or the `pc_token` cookie set by `/`). Comparison is constant-time (`hmac.compare_digest`). Rotating the token via the "Regenerate token" button invalidates every existing URL.

**Logging.** Every accepted control action emits a line to `phantomclick.log`: `monitor_control action=start client=192.168.1.42 ok=True`.

**Threats out of scope (LAN-trust model).** No SSL, no rate-limiting, no IP allowlist. The token is the access control. Anyone on the same Wi-Fi who has the URL can view AND (if remote control is on) control. The card text says so plainly.

`MonitorServer.start()` is idempotent — it stops any running instance first, so port/FPS changes restart the server cleanly. `MonitorServer.stop()` is wired into `App.closeEvent` so the listening port is freed before the process exits.

---

## The Engine (`modules/clicker.py`)

Single-threaded event loop running in a daemon thread, plus a watchdog thread for the corner-emergency-stop. All sleeps go through `threading.Event.wait()` so Stop is instant.

Per-cycle dispatch in `_run`:
1. **Recorder mode**: `_peek_recorder_step()` returns the current step.
   - `KIND_PAUSE` → `_human_delay()` + `_wait_with_wander()` + advance.
   - `KIND_TRACK` → `_activate_track_step()` (load PNG into shared tracker, push per-step settings) → poll `_tracker_zone()` until locked → use that zone for this cycle's target.
   - `KIND_COLOR` → `_find_color_target()` snapshots `color_search_rect` (the picked monitor) via a persistent engine `mss.mss()` handle, masks with `cv2.inRange`, and picks a random match via `cv2.findNonZero` — used as a 4×4 cycle zone around the matched pixel.
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

Tracker template + locate loop is **owned by the App**, not the engine — so the user gets a live preview overlay even while idle. The engine just reads `tracker.snapshot_state()` and mutates the same shared TemplateTracker via `_activate_track_step()`. When the engine is running, the App's preview loop and the engine's reads coexist on the same tracker instance.

---

## GUI Architecture (`app.py` + `ui/`)

Landscape PySide6 window, default 1280 × 800 (min 960 × 600), resizable. Three persistent chrome elements wrap one swappable page surface:

- **NavRail** (left, fixed-width) — vertical icon+label list, one entry per page (Click, Record, AI, Hover, Behavior, Hotkeys, Timers, Stats, Monitor, Settings, Help). Active item shows a teal left-edge stripe.
- **TopBar** (top, 52 px) — `BRAND   ◉ status pill   [▶ START] [■ STOP]   Esc to abort   ⌘K   👁 ON/OFF`. Status pill, START/STOP, and Esc hint cluster on the right (the spare horizontal space sits between brand and pill).
- **Page stack** (center) — one page per nav item; switching the rail just swaps the central widget.

### Two parallel UI patterns
The pages split cleanly into two visual languages — see *"When to use which pattern"* below. Mode pages (Click / Record / AI) use **Card → Section → Field → action row**; config pages (everything else) use the flatter **GroupHeader → SettingsGroup → SettingsRow** rhythm.

### Tracker preview overlay
While idle in Record mode, the App's tracker loop runs `locate()` at the active step's `update_rate_hz` and a `QTimer` tick redraws a translucent click-through `QWidget` box following the target. Color encodes state: blue (preview, locked), orange (preview, searching), teal (engine running, locked). Overlay is hidden when the user removes the preview step (`_cleanup_removed_track_step`) and respects the topbar `👁 ON/OFF` master toggle.

### Scrolling
Page contents that overflow live inside a `QScrollArea` per page — each is independent, so wheel events naturally route to whichever scrollable the cursor is over. No custom router needed (the Tk `_smooth_scroll_router` glue is gone with the CTk migration).

---

## Humanization (`utils/humanizer.py` + `fatigue.py` + `idle_wanderer.py`)

All controlled by a single `realism` dial 0..1 in the GUI; `_apply_realism()` derives every per-feature value (frequencies, durations, intensities) so users don't need to think about Advanced unless they want to.

- **Movement**: Bezier curves with 1–2 random control points, ease-in-out velocity, ±1–2 px wobble, optional overshoot + correction.
- **Click timing**: 20–80 ms pause before the button fires; 40–120 ms gap between double-click halves.
- **Inter-click delay**: log-normal distribution centered low in the user's range, with an upper soft-clamp tail (matches real human inter-action timing studies).
- **Fatigue**: gradual multiplier on movement / delay times that grows with click count, plus scheduled "break bursts" — multi-second sleeps every 40–70 clicks (configurable).
- **Idle wander**: cursor occasionally drifts to a random point in (or near) the zone *between* clicks.
- **Hover zones**: rare visits to other on-screen regions where the cursor dwells without clicking.
- **Distraction spike**: occasional 3–12 s "looked away" pause every 60–180 clicks at high realism.
- **Muscle memory**: first click of a session is ~20 % slower than typical; movement duration decays exponentially toward floor by ~click 10.
- **Anti-cluster**: targets are repelled from the last 10 click points so distribution doesn't cluster on a Gaussian peak.
- **Micro-jitter tick**: between waits, occasional 1-px nudges to mimic mouse-sensor noise (a frozen cursor is a strong tell).
- **Post-click micro-wander**: 5–30 px curved drift right after every click.

---

## Hotkeys (`modules/hotkey_manager.py`)

Two independent global hotkeys, captured by a `pynput.keyboard.Listener` running in its own thread. Defaults: **F6** = Start, **F7** = Stop. Both rebindable from the Hotkey card; the rebind UI captures the next keypress (Escape cancels, can't bind to the other action's key, can't be empty). Persisted as `hotkey_start` / `hotkey_stop` in `config.json`.

The corner-emergency-stop watchdog spins separately: any time the cursor lands in a screen corner (within 2 px), the engine stops immediately.

---

## Key Timers (`modules/key_timer.py`)

Passive concurrent keypresses for things like potion macros: *"press Z every 6 minutes while my farming sequence runs."* They are **not** steps — they don't advance recorder state, don't move the cursor, and aren't gated by the active step. Each `KeyTimer` is `{key, interval_min, interval_max, enabled}`. Combo strings are `+`-joined (`"z"`, `"f1"`, `"ctrl+z"`, `"ctrl+shift+f5"`); `parse_combo` validates them and resolves modifiers via `pynput.keyboard.Key`.

When `Clicker.start()` succeeds, it spawns one daemon thread per enabled+valid timer running `run_timer_loop`, which sleeps `random.uniform(interval_min, interval_max)` between fires using the engine's shared `_stop` event. On `stop()` (or any natural exit of `_run`) `_stop.set()` reaps every timer cleanly. Timers fire only while the engine is otherwise running — they don't keep the engine alive on their own. Persisted as `key_timers` in `config.json`.

---

## Configuration

`config.json` lives next to the running script / exe. `load_config()` deep-merges with `DEFAULTS` and runs auto-migrations (legacy `hotkey_toggle` → split keys, legacy `is_pause` → `kind`, legacy global tracker → KIND_TRACK step).

Selected keys:

```jsonc
{
  "hotkey_start": "f6",
  "hotkey_stop": "f7",
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
  "key_input_backend": "serial_hid",   // "sendinput" | "interception" | "serial_hid"
  "serial_hid_port": "COM3",
  "ai_bot_slug": "menaphos_acadia",
  "ai_tick_rate_hz": 5.0,
  "ai_monitor": 1,
  "ai_dry_run": false,
  "show_zone_overlay": true,
  "monitor_token": "...",                // set on first Monitor enable
  "monitor_port": 8765
  // ... realism-derived per-feature toggles, intensities, durations
}
```

Saved on every meaningful change (slider release, button click, zone draw). No explicit Save button.

---

## Color & Type (`ui/theme.py`)

Refreshed 2026 palette. Warm-neutral slate surfaces (no blue cast), single teal accent (`#22d3ee`) for primary CTAs / active stripes / section eyebrows / slider thumbs — used sparingly to keep its meaning ("this is the actionable / current thing") legible. Segoe UI Variable Text for body, Variable Display for headers / titles. Three-tier type scale: 11 px section eyebrow (uppercase, teal, +1 px tracking) / 13–14 px field labels and body / 12 px tertiary hints. Cards use a 14 px corner radius, buttons 10 px, inputs 8 px. Section grid is on an 8 px base with 24 px between sections and 12 px between fields within a section.

Palette migrates automatically: users who haven't customized colors pick up the new accents on next launch; custom-picked colors are left alone.

---

## When to use which pattern

PhantomClick uses two parallel UI patterns. Pick one when adding a new tab; do not mix them within a single page.

**CARD-BASED (mode pages):**
- Click, Record, AI
- Use Card → Section → Field → action row
- Components: `Card`, `SectionLabel` (or `Section` for richer headers), `Expander`, step-card active stripe (3 px teal left edge on the active card)

**FORM-ROW (config pages):**
- Hover, Behavior, Hotkeys, Timers, Stats, Settings, Help
- Use `GroupHeader` → `SettingsGroup` → `SettingsRow`
- Tighter rhythm, flatter hierarchy, no cards

**HYBRID:**
- Monitor — wraps a `Card` (for the listening-state stripe and a header `StatePill`) but every internal row is canonical `SettingsGroup` + `SettingsRow`. The Card chrome is justified by the active-state visual signal that doesn't fit a flat form-row page. Documented hybrid; do not extend the pattern further unless a similar live-state need appears.

When adding a new tab, classify it as **"mode"** (an active workflow that has live state — running engine, live preview, log output, current step) vs. **"config"** (set-and-forget settings the user adjusts then forgets about). Use the corresponding pattern. Do not mix the two within one page — the visual languages don't compose cleanly.

## Design system patterns

### Active-state stripe — 3 px teal `[active="true"]` (or `[expanded="true"]` / `[listening="true"]`)

A 3 px teal left edge on a container marks "this thing is currently doing work." Used by:
- Nav rail items (active page)
- Step cards in Record (`[expanded="true"]` and `[active="true"]`)
- Monitor card (`[listening="true"]`) when the streaming server is running
- Behavior master groups (`[active="true"]` on `SettingsGroup`) when the master switch is on

Implementation: a per-attribute QSS rule (`QFrame#card[listening="true"]`, `QFrame[role="settings-group"][active="true"]`, etc.) plus a tiny `set_active(bool)` / `_set_listening(bool)` helper on the widget that sets the property and re-polishes. **Reuse the existing pattern**; don't invent a parallel mechanism.

### Warn-outline buttons — `variant="warn-outline"`

Amber border + amber text for actions whose side effect is destructive enough to deserve a visual cue but common enough that a confirm dialog would be friction (Monitor's "Regenerate token" — invalidates existing phone URLs). **Always pair with a tooltip** that explains the consequence in plain language. If the action is rare AND irreversible, prefer a `QMessageBox` confirm dialog instead.

### Disclosure widgets — `Expander` only

The `Expander` widget owns its own chevron via an internal `_ExpanderToggle` row. **Never bake `▸` or `▾` into the label string** — it renders a duplicate chevron. Pass the label only:

```python
self.expander = Expander("Advanced — watchdogs & auto-camera")  # correct
self.expander = Expander("▸  Advanced — watchdogs & auto-camera")  # WRONG — double chevron
```

Action buttons (Test step, Add view, etc.) **never** use a `▸` prefix — it reads as a disclosure affordance and confuses the click target. The button shape itself is the affordance.

### Format helpers — display vs. edit

`ui/format.py` is the single source of truth for **display** formatting: `fmt_count`, `fmt_delay`, `fmt_position`, `fmt_rate`. `ui/screen_utils.py` owns `screen_label` for monitor enumeration. Before adding a new f-string in a card, **check these modules first**.

**Important principle: canonical formatters apply to display surfaces, not edit surfaces.**
- Display surfaces (chips, badges, readouts, status pills): use the canonical helper. They show *settled* values where consistency matters.
- Edit surfaces (spinboxes, sliders, text inputs): respect the user's chosen unit and precision. A timer set to "every 15 min" should edit in minutes, not in `fmt_delay`'s 3-decimal seconds. Forcing a canonical format on an edit field destroys the user's mental model of the value they're tuning.

### Section labels and group headers

Section eyebrow labels (Click / Record / AI internal cards) and group headers (form-row pages) both render in **teal at 11 px uppercase**. Drop trailing hairline rules — the teal uppercase carries the section marker by itself; half-rendered rules read as bugs.

## Sprint history

The 2026 design pass shipped in six focused sprints:

- **Sprint 1 — Token polish.** Group headers and section labels routed to `t.ACCENT`. `stat-value` font tokenized to `t.SIZE_STAT_VALUE` with explicit `QFont` lock (QSS attribute selectors lose to inherited fonts). Help page key labels demoted from `t.ACCENT` → `t.ACCENT_TEXT`. Click divider annotated as intentional rhythm whitespace.

- **Sprint 2 — Format utilities.** Extracted `screen_label()` to `ui/screen_utils.py` (Monitor and Settings had diverged copies — the Monitor copy never normalized 3-letter EDID codes like `"AUS"` → `"ASUS"`). Added `fmt_count`, `fmt_position`, `fmt_rate` to `ui/format.py`. Stats tab values normalized to canonical formatters (3-decimal delays, `CPM` suffix, locale comma). 27 unit tests in `tests/test_format.py`.

- **Sprint 3 — AI tab consistency.** Replaced the Hero card's custom `QPushButton` setup-notes toggle with the canonical `Expander` widget (gains 220 ms `OutCubic` slide animation). Tokenized hardcoded `4 px` spacing to `t.SP_XS`. Switched bot dropdown selection-bg from `ACCENT_DIM_FALLBACK` (solid hex) to `ACCENT_DIM` (rgba) for visual consistency. **Found and fixed a double-chevron bug** in the Config-section Expander (label was being constructed as `"▸  Advanced — …"` while `_ExpanderToggle` already renders its own chevron).

- **Sprint 4 — Monitor card refactor.** Migrated from ~180 lines of handcrafted `QHBoxLayout` rows to declarative `SettingsGroup`/`SettingsRow`. Extended `SettingsRow` with `mono_desc=False` kwarg (renders desc as mono primary instead of quiet tertiary — used by the Phone URL row). Added `[listening="true"]` active stripe pattern. Added `variant="warn-outline"` button variant for the Regenerate-token action. Replaced explicit `QFrame divider` with `addSpacing`.

- **Sprint 5 — Timers polish.** `TimerRow` was already honoring the `SettingsRow` contract via `role="settings-row"` + `set_last()` + `SettingsGroup` integration; the audit had pattern-matched on widget names and missed the actual contract compliance. Minimal three-edit fix: canonical `t.ROW_PAD_Y` (was `-2`), tokenized the 36 px row-2 indent into `_BADGE_W + t.SP_SM`, mono font on the interval spinbox.

- **Sprint 6 — Final polish.** Behavior master groups now light up the `[active="true"]` left stripe on their `SettingsGroup` when the master switch is on (Stop-after's two masters OR-aggregate). Added `SettingsGroup.set_active(bool)` and the matching QSS rule, mirroring Sprint 4's MonitorCard pattern. Documented all of the above in this file.

### Audit retrospective

The audit's TimerRow finding ("MEDIUM, structural refactor") was based on a pattern-matched read of the widget name and two-line layout. The actual implementation already honored the `SettingsRow` contract (role attribute, last-row management, `SettingsGroup.add_row` integration). **Lesson:** audit findings are hypotheses; verify against the implementation before sizing the fix. A widget that doesn't subclass `SettingsRow` can still satisfy its visual contract — and a widget that does subclass it can still violate the visual contract. Subclass relationships are weaker than role/QSS contracts in this codebase.

## Process for new tabs or major UI changes

1. Classify the surface as **mode** / **config** / **hybrid** (and justify hybrid).
2. Use the corresponding pattern stack (Card or GroupHeader/SettingsGroup).
3. Read `ui/format.py` and `ui/screen_utils.py` before inventing local formatters.
4. Read this section and confirm proposed changes don't violate established patterns. If a new pattern is needed, propose it as an addition here **before** implementing.

---

## Critical Rules

1. **Mouse must physically move.** No coordinate-only clicks; the cursor visibly travels.
2. **All movement looks human.** Bezier, speed variation, jitter, overshoot. Never a straight line at constant speed.
3. **Hotkeys work globally** — even when a fullscreen game has focus.
4. **Stop is instant.** Every wait goes through `Event.wait()`; no `time.sleep()` in the engine.
5. **GUI never freezes.** Engine, watchdog, tracker, hotkeys all run on background threads.
6. **No outbound network.** No telemetry, no updates, no analytics. The opt-in Monitor tab serves screen + status to the user's own devices on the local network, but only when the user explicitly enables it; that's the single carve-out.
7. **Zone overlays are click-through** — they never intercept the actual game's clicks.
8. **Config persists between sessions** via local JSON.
9. **Track templates are per-step**, keyed by `step.step_id`, stored in `templates/`.
10. **Multi-monitor aware where it matters.** Click / Track / Color modes capture from `monitors[0]` (the virtual screen union), so a zone drawn on a secondary monitor is captured correctly. AI mode pins to a single monitor index (`ai_monitor`) since the bot's coordinate logic assumes one frame.

---

## Build & Package

```bash
pip install -r requirements.txt
python main.py                                         # dev run
pyinstaller --onefile --windowed --name PhantomClick \
    --icon assets/phantomclick.ico \
    --add-data "ai/tasks/library;ai/tasks/library" \
    --add-data "rs3vision;rs3vision" \
    --collect-binaries rs3vision \
    main.py                                            # single-exe build
```

The `--add-data "ai/tasks/library;..."` flag bundles every `*.task.yaml` +
its companion `.py` bot script. The `rs3vision` collect/data flags ship
the prebuilt `_rs3vision.pyd` Rust core (Python 3.11-only — pin your
venv to 3.11). Without these, the AI tab will load empty and any bot
that imports `rs3vision as rv` will crash at startup.

---

## Out of Scope (intentional)

- Scripting language / external macro DSL (recorder steps + AI bot scripts cover the use cases without inventing a new language).
- Outbound network features (telemetry, auto-update, analytics, cloud sync). The Monitor tab's local LAN HTTP server is the single carve-out and is opt-in.
- Auto-update mechanism.
- Cross-platform support — Windows-only by design (Arduino HID + NXT context don't generalize).
