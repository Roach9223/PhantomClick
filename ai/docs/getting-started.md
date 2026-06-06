# Getting started

Welcome. rs3vision Studio is a **visual colour-automation tool** — you
drag blocks onto a canvas, wire them together, press Play, and watch the
runtime execute your script against a live screenshot of whatever game
(or app) you're targeting.

No coding required for the basics. Power users can drop to Python any
time by `import rs3vision as rv`.

---

## The four panels

| Panel | Where | What it's for |
| --- | --- | --- |
| **Block library** | Left dock | Every action you can take, grouped by category. Double-click or drag onto the canvas. |
| **Node editor** | Centre | Your script. Blocks as nodes, wires as data/trigger flow. Right-click a node for per-block actions. |
| **Live visualizer** | Right dock | Real-time view of your target monitor. Click a pixel to pick its colour, drag a rectangle to set an ROI. |
| **Log panel** | Bottom dock | Two tabs: *Messages* for text output, *Block I/O* for a structured tick-by-tick view of every block's inputs and outputs. |

---

## Build your first script in 2 minutes

1. **Top toolbar → Target monitor**: pick the display showing your target app.
2. **File → New from Template → "Click a color loop"**: gives you 6 nodes pre-wired.
3. **Live visualizer**: click any pixel with the colour you want to click on. The hex value is copied to your clipboard *and* applied to the Find Color block's `target` param if that node is selected.
4. **Optional: drag a rectangle** around the area you want the script to search in, then click **Use as default ROI**. Dramatically cuts false positives.
5. **F5 to Play.** Watch the visualizer overlay detections in real time.
6. **F6 or Esc anywhere** to stop.

---

## Before you run anything against a real game

- **Enable dry-run mode** (🧪 toolbar checkbox) on your first run. Click
  blocks will log `[dry-run] would click (...)` instead of actually
  clicking. Lets you confirm the logic without any input firing.
- **Crank the tick rate DOWN** to 1-2 Hz while debugging. You can watch
  Block I/O tick-by-tick.
- **Esc is a global kill-switch** while a script is running. Works from
  any window, any app. You don't need to alt-tab back to the Studio.

---

## "What do I do when something breaks?"

- **Visualizer shows "No frame yet"** and the log says `graph is empty`:
  drop at least an `On Start` block.
- **Script runs but nothing happens**: check the Block I/O tab. Is each
  tick actually getting to your action block? If not, a wire's missing
  between trigger outputs and trigger inputs.
- **Find Color keeps returning found=false**: increase `tol`. The actual
  rendered colour on screen is usually *not* the hex value you set in
  the game UI (anti-aliasing + gamma shifts it). Use the visualizer
  pipette to pick the real rendered colour.

See the **Troubleshooting** tab for more.
