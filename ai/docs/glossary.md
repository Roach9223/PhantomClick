# Glossary

**anchor**
The primary reference pixel in a DTM or bitmap template. The matcher scans
every candidate position for the anchor colour first (cheap), then validates
the surrounding structure. A good anchor is a rarely-occurring colour in
the template — reduces false candidates to a minimum.

**bitmap matching**
Template matching where the reference is a small PNG of exact pixels. The
runtime slides that PNG across the frame looking for places it matches
within a per-channel tolerance. Good for UI icons, fixed sprites.

**BGR**
Byte order rs3vision uses for pixels — *Blue, Green, Red* instead of the
more-familiar RGB. Matches how Win32 BitBlt and OpenCV hand us the frame
buffer, zero copies required. When a block's `target` is specified as a
hex value, it's `0xRRGGBB` (human-friendly) — the runtime converts internally.

**block**
A single executable unit on the canvas. Every block has some combination
of input ports, output ports, and user-editable parameters.

**centroid**
The mean-position point of a cluster. When you "pick the biggest cluster",
the centroid is the average x/y you'd click to land in the middle of it.

**cluster**
A group of pixels close together (Chebyshev distance ≤ *N*). rs3vision's
`tpa.cluster` merges hit points into clusters so you can reason about
"the red dot" instead of "each red pixel".

**confidence**
A `[0, 1]` score attached to every detection. Rough interpretation:
  - `1.0` = exact match
  - `0.7` = comfortable match
  - `0.5` = at the tolerance boundary
  - `<0.5` = probably noise
Most blocks expose confidence on an output port.

**CTS (Colour Tolerance Speed)**
rs3vision's pixel-matching modes, in order of cost and quality:
  - **CTS1** — rectangular RGB-channel tolerance. Fastest, brittle under AA.
  - **CTS2** — HSL cylindrical tolerance with hue/sat multipliers. Best
    default for antialiased game text and UI.
  - **CTS3** — CIE L\*a\*b\* ΔE76 with lightness multiplier. Most
    perceptually accurate; slowest.

**dry-run**
Toolbar toggle. While on, `Click` / `Move Cursor` / `Press Key` blocks log
`[dry-run] would click at (x, y)` instead of firing real input events.
Safety net for testing new scripts.

**DTM (Deformable Template Matching)**
Template matching by a handful of relatively-positioned coloured points
rather than a full pixel bitmap. More tolerant of anti-aliasing and minor
lighting changes than bitmap matching; cheaper at runtime.

**frame**
One `(H, W, 3) uint8` BGR numpy array — a single snapshot of a monitor.

**frame diff**
Byte-level comparison between two frames, 8×8 tile by 8×8 tile. Used to
cheaply detect "did anything change in this region?" before running
expensive OCR or matching.

**input backend**
Which API a script uses to click / type. Two options in the Studio:
  - **PostMessage** — Windows message posting. Background-friendly —
    works even if the target window isn't focused. RS3-specific.
  - **real** — `pyautogui` + `pynput`. Moves the real cursor, real
    keystrokes. Works with any Windows app.

**kill-switch**
The global Escape hook. Pressing Esc anywhere (any app, Studio doesn't
need focus) halts a running script. Powered by pynput's system-wide
keyboard listener.

**mss**
The Python library we use for screen capture. Fast multi-monitor BitBlt.
Each monitor has an integer index (0 = virtual "all monitors", 1 = primary,
etc.).

**OCR**
Optical Character Recognition. rs3vision's approach: compile bitmap fonts
from captured game text (tools in `rs3vision-tools/`) then match glyph
bitmaps with a perceptual hash.

**port**
A named connection point on a block. Two kinds:
  - **trigger** (yellow) — carries control flow. When an upstream trigger
    fires, the downstream block executes.
  - **data** (blue) — carries values (frames, points, lists, strings).

**ROI (Region of Interest)**
An `(x, y, w, h)` rectangle scoping a scan to a sub-region of the frame.
Massive speed + accuracy win: scan only the chatbox for chat events,
only the minimap for compass, etc. Drag on the visualizer → Use as default
ROI → every block with a blank `roi` param inherits it.

**.rvf**
rs3vision's compiled bitmap font format. Binary, ~20 KB per font. Built
with `rs3vision-tools/compile_font.py`.

**.rvscript**
The Studio's script file format. YAML, human-readable, diff-friendly.
Contains `nodes`, `edges`, and header metadata. You can hand-edit it in
any text editor.

**template**
Reusable rule set for matching. Two flavours:
  - **Bitmap template** — a PNG of the thing to find.
  - **DTM template** — a YAML describing anchor + relative points.

**tick**
One full walk of the graph by the runtime. The tick-rate spinner in the
toolbar controls how often ticks happen (default 5 Hz = 5 ticks per second).
Each tick emits `tick_started`; each block executed during that tick emits
`block_executed` with its inputs + outputs.

**TPA (Two/TPointArray)**
From Simba — a list of `(x, y)` points. rs3vision's `tpa` module groups
these (clustering, bounds, centroid, morphology). The building block for
"where is the thing?" logic once you have a pile of matched pixels.

**tolerance (tol)**
How permissive a match is. Depends on the CTS mode:
  - CTS1 — tol is per-channel RGB delta (0-255)
  - CTS2 — tol is a combined HSL threshold (typ. 15-30)
  - CTS3 — tol is Lab ΔE (typ. 5-20)

**trigger**
A control-flow signal. When a block emits on a trigger output port, any
block connected to that wire runs next. Distinct from data values which
just carry information.
