# Changelog

What's shipped, in reverse chronological order.

---

## Unreleased (in progress)

### Sprint 5 — Studio-hosted MCP endpoint (graph edits) 🤖
- **New toolbar toggle** — 🤖 **MCP**. Default OFF. Tick to launch an
  HTTP MCP endpoint at `127.0.0.1:3031/mcp` so Claude Code can edit
  the live graph.
- **12 mutation tools** exposed: `graph_state`, `graph_ids`,
  `set_param`, `add_node`, `delete_node`, `connect_ports`,
  `disconnect_ports`, `apply_recipe`, `undo`, `redo`, `save_script`,
  `server_info`.
- Every edit: logged with `🤖 MCP edit: …` prefix, flashes the status
  bar, lands on the NodeGraphQt undo stack (`Ctrl+Z` reverses Claude's
  edits like your own).
- Port override via `RS3VISION_MCP_PORT` env var.
- Paired with the Sprint 4 `rs3vision-mcp` stdio server — mutation
  is HTTP, observation is stdio.

### Sprint 3.5 — Real-world test: woodcutting + debug infrastructure
- **Debug log files** — every Studio session now writes to
  `F:\RS3_AI\debug\logs\studio-<timestamp>.log`. Survives crashes,
  rotates to 30 most recent.
- **Screenshot debug folder** at `F:\RS3_AI\debug\screenshots\<day>\`:
  - **📸 Save snapshot** button on the visualizer dock — manual save
    of the current frame, full path logged.
  - Toolbar **📷 Auto-save frames** checkbox — every 10th captured
    frame written to disk while a script runs.
  - **Crash snapshots** — when a block raises during a run, the last
    captured frame is auto-saved with the offending block in the
    filename.
  - 14-day retention + 500 MB disk budget; oldest files purged first.
- **Help → 📂 Open debug folder** and **📝 Open current log file**
  menu entries.
- New recipes: **Chop trees (simple)** and **Chop trees (with
  inventory-full check)**, plus a Help → **Woodcutting** tab with the
  full walkthrough.

### In-app help system 📖
- Tabbed help dialog accessible via **F1** or **Help → Documentation**.
- Auto-generated **Block Reference** — every registered block with its
  description, ports, parameters, and inline example.
- Tabs: Getting Started, DTM + Bitmap, Recipes, Block Reference,
  Glossary, Keyboard, Changelog, Troubleshooting.
- Per-tab search box with Next/Prev navigation.
- **Right-click → 📖 Help for this block** jumps to that block's page.
- **Error log links** — common error messages become clickable and open
  the help at the relevant troubleshooting entry.

### DTM + Bitmap matching
- `rs3vision_studio.algorithms.bitmap.find` — sliding-window template
  match with CTS1 anchor prefilter. Fast on 4K scenes.
- `rs3vision_studio.algorithms.dtm.find` — anchor + relative-point
  matcher. YAML template format.
- New blocks: **Find Bitmap**, **Find DTM** — no longer stubs.
- Visualizer buttons: **💾 Save ROI as bitmap** and **🎯 Create DTM
  from ROI** — build templates from visually-selected regions.

### Studio UX polish
- **Welcome tour** on first launch (re-openable from Help menu).
- **Tick-rate spinner** (1–30 Hz) in toolbar, live-adjustable during runs.
- **Dry-run toggle** 🧪 — logs clicks without firing them.
- **Global Esc kill-switch** — stops scripts from any focused window.
- **Colour pipette** — click any pixel on the visualizer to copy hex to
  clipboard + auto-apply to a selected Find Color / Find All Clusters /
  Count Color / Read Text block.
- **Region picker** — drag on visualizer → Use as default ROI → every
  block with a blank `roi` param scopes to that rectangle.
- **Copy / Cut / Paste / Duplicate / Undo / Redo** on the graph
  (Ctrl+C/V/X/D/Z/Y).
- **Right-click node → Run Once (Debug)** — execute a single block in
  isolation with current params.
- **Port colour coding** — triggers yellow, data blue.
- **Node tooltips** — hover any node for description + identifier.
- **Starter templates** — File → New from Template → Click a color loop,
  Wait for a color, OCR and compare.
- **Auto-seeded On Start** — new scripts start with the entry block in place.
- **Multi-monitor picker** in toolbar with live preview thumbnail.
- **Always-on visualizer preview** at 3 Hz, independent of script execution.

### Studio foundations (Sprints 1–2)
- Main window with dock panels: block library, node editor, live
  visualizer, tabbed log panel.
- 22 blocks across 9 categories (Flow, Color, TPA, Vision, OCR, Input,
  Feature, DTM, Bitmap).
- `.rvscript` YAML format for scripts.
- Graph runtime with per-tick telemetry.
- Drag-and-drop from block library onto canvas.

### Library (rs3vision)
- Rust core: CTS1/2/3 color matching, TPA, frame delta, OCR primitives
  with `.rvf` font format, recognizer pipeline with digraph handling.
- PyO3 bindings with numpy zero-copy.
- 59 Rust unit tests + 24 Python integration tests.

---

## Project origin

Pivoted from **"a specific RS3 bot"** to **"a modern Simba-inspired
colour-automation Studio"** on 2026-04-12. Library (rs3vision) lives
in `rs3vision-rs/`; Studio app lives in `rs3vision-studio/`; pre-pivot
code archived to `_legacy/`.
