# PhantomClick — Long-Term Game Plan

The durable roadmap for the bot project. Three phases, each gated on the previous. Hardware is owned; no purchases required.

For the active task list (Phase 1 instrumentation + documentation), see `.claude/plans/`. For the wiring topology, see `docs/wiring_diagram.md`. For the project's overall spec, see `CLAUDE.md`.

---

## Hardware inventory (already on hand)

| Device | Role | Lives in |
|---|---|---|
| **Elgato PCIe Capture Card** | Frame source for Bot PC, HDMI passthrough to monitor | Bot PC PCIe slot |
| **Captain DMA Fuser** | Reads Main PC RAM via PCIe — invisible to NXT | Main PC PCIe slot |
| **DMA Reader** (USB-C end) | Bot PC consumes memory reads from Fuser | Bot PC USB 3.0+ |
| **KMBox NET** | Dual-host HID controller, USB to Main PC + LAN to Bot PC | Standalone, on LAN |
| Main Monitor | Game display (RS3) | Via Elgato passthrough |
| Bot Monitor | Dev display (Python UI, Ghidra, logs) | Bot PC GPU |
| *Cam Link 4K* | Backup; not in active architecture | Drawer |

Main PC sees only: a monitor (passive HDMI sink), a generic HID device (KMBox NET), a generic PCIe card (DMA Fuser). No software touches RS3.

---

## Phase 1 — Color detection recovery (immediate, ~2 hours)

**Status:** ready to execute.

The current fishing bot can't detect a fishing spot — `find_interactable(roi=POOL_ROI, min_pixels=20)` returns falsy every tick. We instrument the detector so failures explain themselves, then iterate until detection is reliable.

### Steps

1. Add `debug_label: str = ""` kwarg to `find_any_color` + `find_interactable` in `ai/bot/api.py`. When set, log every sample's `hits / clusters / best / px` counts.
2. Wire `debug_label="recast"` into `recast_when_idle` in `ai/tasks/library/menaphos_vip_fishing.py`.
3. Extend `ui/cards/ai_captures.py` 🐛 Debug frame button to dump a side-by-side raw/overlay PNG for Colour captures — every matched pixel highlighted, cluster centroids marked, `min_pixels` threshold annotated.

### Diagnostic table

| Log pattern | Root cause | Fix |
|---|---|---|
| All samples → `hits=0` | Captures don't match live cyan (palette drift, contrast mode off, wrong angle) | Re-capture `contrast_cyan` at the actual pool from the actual camera angle |
| `hits>0` but `clusters=0` | Fragments below `min_pixels` after clustering | Drop `min_pixels` from 20 to 10 in the rule call |
| `clusters>0` but centroid is wrong place | ROI misaligned or `cluster_dist=6` collapsing far-apart pixels | Tighten ROI or drop `cluster_dist` to 4 |
| Strong matches but bot still doesn't click | Detection is fine; problem is downstream | Examine `player_is_animating` gate, idle-grace counter, or tooltip mismatch |

### Verification

1. Apply instrumentation; restart bot in `dry_run=True`; stand at the pool.
2. Tail `phantomclick.log` for `[find_any_color/recast]` lines for ~10 ticks.
3. Match log pattern to the table; apply the indicated fix.
4. Confirm `recasting — cyan centroid=(X, Y)` lines fire consistently with centroids spreading across the pool.
5. Flip `dry_run=False` once detection is reliable.

---

## Phase 2 — DMA + Elgato + KMBox NET stack (long-term, hobby-pace)

The pro setup. All three hardware paths in parallel: DMA for decisions, Elgato for vision cross-check, KMBox NET for input. Chunks ordered by dependency, picked up as evenings allow.

### Architecture summary

- **Frames:** Main PC GPU → Elgato HDMI IN → (passthrough) → Monitor; PCIe bus → Bot PC Python (`cv2.VideoCapture`).
- **Memory:** Main PC RAM ← Captain DMA Fuser ← USB-C → Bot PC DMA Reader ← LeechCore/MemProcFS.
- **Input:** Bot PC bot script → TCP/UDP over LAN → KMBox NET → USB-A HID → Main PC (looks like real mouse + keyboard).

Full wiring topology with port-by-port detail lives in `docs/wiring_diagram.md`.

### Chunk 1 — KMBox NET backend (~1–2 days)

- New `modules/kmbox_net_backend.py` implementing existing keyboard backend interface (`send(vk, key_up)`) + new `send_mouse(x, y, button)` method, all over LAN to KMBox's IP using `kmNet` Python API.
- Add `key_input_method = "kmbox_net"` config option.
- Wire mouse path through `ai/input/clicker_actuator.py` (AI bots) and gated into `utils/humanizer.py` (Click/Record modes).
- Verify standalone: `kmNet.move(500, 500); kmNet.left(1)` lands a click in Notepad on Main PC, *then* RS3.

### Chunk 2 — Elgato PCIe FrameSource (~1 day)

- New `ai/input/elgato_frame_source.py` implementing `next_frame() -> np.ndarray` via `cv2.VideoCapture(<idx>, cv2.CAP_DSHOW)`.
- Wire via existing `BotRunner.set_frame_source()` (`ai/bot/runner.py:908`). `mss` stays as fallback for Main-PC-local runs.
- Verifies the full Bot-PC pipeline before DMA arrives: Bot PC reading Elgato frames + sending KMBox commands = a complete current-style bot running on the safe side.

### Chunk 3 — DMA reader integration (the long pole)

- Hardware: install Captain DMA in Main PC, connect to Bot PC via USB-C.
- Software: `LeechCore` + `MemProcFS`. New `ai/dma/` subpackage exposing `dma.read_player()`, `dma.read_npcs()`, `dma.read_inventory()`, `dma.read_camera_matrix()`.
- Offsets are the hard part — see Phase 3.

### Chunk 4 — Refactor bots to world-coord logic

- Rules stop calling `find_interactable` for primary decisions; call `dma.npcs(name="...")` → filter → `world_to_screen(pos)` → click via KMBox NET.
- Elgato reserved for visual-only signals: modal dialogs, level-up popups, "Lost connection" overlay, prayer-drain warnings.
- New decorator distinction: `@bot.rule(source="dma")` vs `@bot.rule(source="vision")`.

---

## Phase 3 — Offset discovery (gated on Chunk 3 hardware-up)

Reverse-engineering work to find RS3 NXT's struct offsets so DMA reads return meaningful data instead of raw bytes.

### Toolchain

| Tool | Use |
|---|---|
| **Ghidra** | Disassemble `rs2client.exe`, find functions, follow pointers |
| **MemProcFS** | Mount Main PC memory as filesystem on Bot PC — grep, xxd, hex-diff |
| **PCILeech** | CLI to dump RAM regions for offline analysis |
| **Python `pymem` + `LeechCore`** | Iterate offsets quickly without recompiling Ghidra scripts |
| **ReClass.NET** | Visualize memory as C-like structs |

### Workflow

1. **Anchor on known strings.** Skill names, NPC names, item names live in `rs2client.exe` as plain text. Find them in memory → walk pointers backward to find the containing struct.
2. **Cross-reference.** Player struct is adjacent to player name; XP table, inventory, NPC list reachable from there.
3. **Pattern-scan to survive patches.** Copy 32–64 bytes of function instructions (with relative-jump wildcards) into a signature; future patches shift addresses but preserve patterns.
4. **Maintain an offset DB.** `ai/dma/offsets/<patch_date>.yaml` — each entry records `(pattern, offset, target)`. A Python tool re-resolves the DB on each launch and warns when patterns no longer match.

### Realistic timeline

- First `dma.read_player_pos()` returning correct world coords: 2–4 weeks of evenings.
- Full NPC/inventory/item-table API: 1–3 months after that.
- Patch-day re-pinning workflow stable: incremental. Plan on losing one evening per major NXT patch for the first six months.

### What Claude can help with

- Pattern-matcher + offset DB loader code
- Ghidra triage (read disassembly, suggest struct shapes)
- MemProcFS scripting (memory diff between game states, struct boundary discovery)
- NPC/inventory iterators once base pointers known
- Patch-day re-pinning when patterns mismatch

What Claude can't do: physically install hardware, push buttons in Ghidra, or replace real RE experience. First time through is slow regardless of helper.

---

## Considerations folded in along the way

- **Versioning.** `git init` if not already; tag per RS3 patch once Phase 3 is live so offset breakages are bisectable.
- **Backups.** Weekly zip of `bots/<slug>/assets/` and `ai/captures/global/` to cloud — calibration data takes real time to re-collect.
- **Schedule realism.** Even with NXT-blind hardware, 23h/day fishing produces a behavioral fingerprint. Budget breaks, varied sessions, mixed skills.
- **Account isolation.** Separate email, password, ideally payment. Don't link to Main account.
- **Failure dashboard.** Once both phases working, a small Qt or web panel showing `state, last_action_ts, frames/sec, dma_health, kmbox_connected` saves debugging time.
- **Heartbeat alerts.** Webhook → Discord / Pushover when the bot exits unexpectedly.
- **ToS.** RS3 prohibits automation; hardware just changes detection probability. This is documented, not assumed away.
- **Don't build everything at once.** Phase 1 first. Phase 2 chunks one at a time. Phase 3 only after Phase 2 is verified.

---

## Skills & agents (set up as needed)

- **`dma-offset-hunter`** — create when Phase 3 starts. Loaded with RS3 NXT context, struct shapes, LeechCore/MemProcFS API, pattern-scan idioms. Lives at `.claude/agents/dma-offset-hunter.md`.
- **`bot-test-pilot`** — create when Phase 1 detection is verified working. Knows `phantomclick.log` format and `Bot` rule lifecycle. Lives at `.claude/agents/bot-test-pilot.md`.

MCP servers: nothing project-specific off the shelf. Filesystem and GitHub MCPs are optional comforts later, not blockers.

---

## Document map

- **This file (`gameplan.md`)** — durable roadmap, lives in repo, git-tracked.
- **`.claude/plans/<active>.md`** — active planning session (transient).
- **`docs/wiring_diagram.md`** — hardware wiring topology (Mermaid + ASCII).
- **`CLAUDE.md`** — overall project spec; references this file for Phase 2/3 details.
- **`phantomclick.log`** — live runtime log; `[find_any_color/recast]` lines after Phase 1.
- **`ai/dma/offsets/`** — future offset DB once Phase 3 begins.
