# Recipes

Pattern library. Copy, adapt, remix.

---

## "Click the biggest yellow blob I see, forever"

```
On Start → Capture Screen → Find Color (target=0xFFFF00, tol=25)
  → If Found → Click → Wait 300ms
             → else → Wait 500ms
```

Starter template: **File → New from Template → Click a color loop**.

---

## "Only act when I see a specific sprite"

```
On Start → Capture Screen → Find Bitmap (bitmap_path=icon.png, tolerance=8)
  → If Found → Click (point from Find Bitmap)
             → else → Wait 400ms
```

Bitmap matching gives you `point` at the *centre* of the match — ready to
click.

---

## "Detect an anvil regardless of lighting"

```
On Start → Capture Screen → Find DTM (template_path=anvil.yaml)
  → If Found → Click (point from Find DTM)
             → else → Wait 500ms
```

DTM tolerates anti-aliasing and minor colour shifts way better than
colour alone for multi-colour UI elements.

---

## "Read the HP orb and bail if I'm low"

```
On Start → Capture Screen → Read Text (font=small_08.rvf, target=0xFFFFFF)
  → Compare (a=text, b='20', op='<')
    → true → Stop
    → false → Wait 500ms (loop)
```

Requires a compiled `.rvf` font. Build one using the tools in
`rs3vision-tools/` (corpus capture → extract_glyphs → glyph_labeler → compile_font).

---

## "Wait for chat to say something"

```
On Start → Capture Screen → Find Color (target=chat_text_color, tol=20, roi=chat_roi)
  → Compare (a=count, b='0', op='>')
    → true → Log Message ("chat line detected")
    → false → Wait 200ms
```

Scope the `roi` to your chatbox to avoid picking up game-world pixels.
Use the visualizer's drag-to-select + **Use as default ROI** so every
block shares the same chatbox box.

---

## "Click a pattern of items in the inventory"

```
On Start → Capture Screen → Find All Clusters (target=item_color, min_cluster_size=20)
  → Pick Largest Cluster → Centroid → Click
  → Wait 600ms → loop
```

`Find All Clusters` returns every matching blob; `Pick Largest` grabs
the biggest one's points; `Centroid` gives you a click-ready point.

---

## "Do nothing if mouse keyboard keyboard input is risky"

Flip the **🧪 Dry-run** toolbar toggle. Every click/move/keypress now
logs `[dry-run] would click at (123, 456)` instead of actually firing.
Great for sanity-checking scripts under new environments.

---

## "Build a script iteratively"

1. Drop blocks, wire them, set params.
2. **Right-click a node → Run Once (Debug)** — runs *just that block*
   with current params, logs outputs.
3. Adjust params, run again.
4. Once individual blocks work, F5 to run the whole chain.

The Block I/O tab at the bottom shows you exactly what every block
produced on each tick — that's where you debug flow issues.
