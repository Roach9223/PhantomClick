# Woodcutting walkthrough

A real end-to-end test of the Studio: get a tree-chopping script
running on a live RS3 window, using only the blocks that ship with
the Studio today.

This is the *first script you should write* — it teaches the entire
loop (capture → detect → click → wait), and you'll keep coming back
to the same pattern for every other automation.

## What you'll build

Two recipes are bundled:

| Recipe | Blocks | What it does |
| --- | --- | --- |
| **Chop trees (simple)** | 7 | Loops capture → find brown trunk → click → wait. No stop condition. |
| **Chop trees (with inventory-full check)** | 10 | Adds an OCR branch that reads the chatbox and stops when "inventory is full" appears. |

Start with **simple**. Promote to **inventory check** once chopping
itself is reliable.

## Out-of-scope for now

Don't try to add these yet — they need things we haven't shipped:

- **Walking to/from a bank.** Needs DTM templates for the bank booth
  and minimap navigation. Manually re-position between runs for now.
- **Multi-tree rotation.** Pick one patch you can see, run, restart.
- **Anti-bot pauses.** The plain `flow.wait` is fine for solo testing.

These all become tractable once the DTM template library and the
labeled `plain_11.rvf` font are in place.

---

## 1. Pick your monitor

The Studio targets one monitor at a time. Top toolbar → **Target
monitor** dropdown → pick the one with RS3 on it.

The right-side **Live visualizer** dock starts showing that monitor at
~3 Hz immediately — confirm RS3 is on screen and looks normal there.

## 2. Pick a tree-trunk colour

1. Stand near a few trees in-game.
2. On the visualizer, **single-click any visible brown trunk pixel**.
3. The status bar flashes the picked hex (e.g. `0x4A2E1A`) and copies
   it to the clipboard.
4. If you have a **Find Color** node selected on the canvas, the hex is
   also written into its `target` param automatically.

> **Tip:** trunks read as several different browns depending on
> shading. Pick a mid-tone — too dark catches every shadow, too light
> catches dirt paths.

## 3. Restrict the search to a region of interest

The default ROI keeps the search away from chrome, NPCs, and the
inventory panel.

1. On the visualizer, **click-drag a rectangle** around just the patch
   of trees you want to chop.
2. Click **📐 Use as default ROI**. The rectangle stays visible in cyan.

Every block with a blank `roi` param will now scope to this rectangle.
Clear it with **✕ Clear ROI** when you want full-screen scanning back.

## 4. Drop the recipe into the editor

**File → New from Template → Chop trees (simple)**

You'll see seven nodes already wired up. The interesting params:

- `target` — the trunk hex you picked.
- `tol` — colour tolerance. Start at `22`. Higher = more permissive.
- `min_cluster_size` — ignore detections smaller than this many pixels.
  Start at `30` to skip tiny dirt patches.
- `ms` (Wait) — how long to wait after clicking. Trees take ~6 seconds
  to chop in RS3 — `6000` is a reasonable start. Adjust per tree type.

## 5. Sanity-check with Run-Once

Right-click the **Find Color** node → **▶ Run Once (Debug)**. The
visualizer overlays a yellow box on every cluster it detected. Tune
`tol` and `min_cluster_size` until only trees light up.

## 6. Dry-run

Toolbar → **🧪 Dry-run** → press **F5**. The script runs but Click /
Move blocks only log what they *would* do. Watch the log:

```
🧪 [dry-run] would click left at (1432, 612)
```

Cross-reference the coordinates against the visualizer overlay. If
clicks land on actual trees, you're good.

## 7. Live run

Untick Dry-run → **F5**. Within ~200 ms a real click should fire on a
trunk. The character starts chopping.

**To stop:** press **F6** (Studio focused) or **Esc** (any window
focused — the global kill-switch). Both halt cleanly.

## 8. Save snapshots when something looks off

Things rarely work first try. When the script clicks the wrong place:

- **📸 Save snapshot** on the visualizer dock writes the current frame
  to `F:\RS3_AI\debug\screenshots\<today>\manual_HHMMSS_mmm.png`.
  The path goes to the log so you can copy-paste it.
- Toolbar **📷 Auto-save frames** dumps every 10th tick automatically
  while the script runs — handy for after-the-fact analysis.
- If a block raises an exception, the runtime auto-saves the last
  captured frame as `error_<block>_HHMMSS_mmm.png`.

Helpful when sharing a problem: paste the path and the snapshot. The
log file (Help → 📝 Open current log file) goes well alongside.

## 9. Promoting to the inventory-full check

Once chopping is reliable, **File → New from Template → Chop trees
(with inventory-full check)**. It adds a parallel OCR branch that
reads the chatbox and stops the script the moment "inventory is full"
appears.

This branch is gated on having a compiled `plain_11.rvf` font — see
**Help → DTM + Bitmap → Fonts**. Until you build one, the OCR branch
silently no-ops; the chop branch keeps running.

To wire the OCR scope:

1. Drag-select your chatbox region on the visualizer.
2. Read the rect from the log line (`Selection: 12,820 480x100 ...`).
3. Click the **Read Text** node, set its `roi` param to that exact
   `12,820,480,100`.
4. Set `target` to the chatbox text colour you care about (default
   `0xFF0000` red — adjust for your filter setup).

## Known limitations (be honest with yourself)

- **No banking.** Inventory-full triggers Stop, not "walk to bank".
- **No re-spawn handling.** If your only nearby tree is chopped down,
  the script clicks empty space until it finds another match.
- **No anti-detection.** Plain waits are predictable. The user is
  responsible for any consequences — this Studio is closer to
  AutoHotkey than to a stealth bot.
- **One monitor at a time.** Studio targets one screen — it doesn't
  hop between them.

## Where things are saved

| Thing | Location |
| --- | --- |
| Recipes | `rs3vision_studio/recipes/*.rvscript` |
| Your saved scripts | wherever you Save As (default: `examples/`) |
| Bitmap templates | `rs3vision-studio/templates/bitmap/*.png` |
| DTM templates | `rs3vision-studio/templates/dtm/*.yaml` |
| Compiled fonts | `rs3vision/templates/fonts/*.rvf` (in the venv) |
| Snapshots | `F:\RS3_AI\debug\screenshots\YYYY-MM-DD\` |
| Log files | `F:\RS3_AI\debug\logs\studio-<timestamp>.log` |

Help → 📂 Open debug folder opens that root in Explorer.
