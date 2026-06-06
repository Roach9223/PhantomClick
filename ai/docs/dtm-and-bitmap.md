# DTM and Bitmap matching — when single colours aren't enough

Most game UI elements have more than one colour. An anvil isn't just
"orange" — it's orange *next to* grey *above* dark-grey. A bank booth
has a gold border, brown wood, specific icon pixels. Trying to match
any of these with single-colour scanning produces endless false
positives.

**Two higher-level primitives fix this**: DTM and Bitmap matching.
Both ship as Studio blocks.

---

## Bitmap matching

**What it is**: you save a small PNG of what you're looking for.
The runtime searches for every place that exact pixel pattern
appears in the frame, up to a per-channel tolerance.

**Good for**: UI icons, fixed sprites, consistent text labels.

**How to use it**:

1. Press 📸 Capture in the visualizer (or just wait for the live preview).
2. **Drag a rectangle** around the thing you want to find.
3. Click **💾 Save ROI as bitmap**. A PNG is saved in
   `rs3vision-studio/templates/bitmap/`.
4. Drop a **Find Bitmap** block into your graph.
5. Set `bitmap_path` to the filename (e.g. `anvil_icon.png`).
6. Wire its `found` output to a condition and `point` to a Click block.

**Tuning**:

| Parameter | Default | What to change when |
| --- | --- | --- |
| `tolerance` | 5 | 0 = exact match. Raise to 10-15 if the sprite appears over different backgrounds or has anti-aliased edges. |
| `roi` | (blank) | Falls back to the Studio default ROI. Tighten to improve speed on large frames. |
| `max_matches` | 10 | Cap on how many hits to return per tick. |

**Performance**: uses a CTS1 anchor prefilter so it's fast on 4K
scenes (typically 10-30 ms per search).

---

## DTM — Deformable Template Matching

**What it is**: a DTM template is a handful of *coloured points* in a
rigid relative layout. Instead of matching every pixel like a bitmap,
the runtime looks for scenes where all the points appear with the
right colours at the right relative offsets.

**Good for**: UI elements that share colours with the background but
have a recognisable *structure*. Anvils, bank booths, menu corners,
prayer icons, tool interfaces, etc.

**Why DTM over bitmap**: DTM tolerates scale shifts and
near-occlusions better — if 4 of your 5 points match cleanly, the
anchor still hits. Also much faster than a bitmap on tight templates.

**How to use it**:

1. **Drag a rectangle** in the visualizer around the thing you want
   to find.
2. Click **🎯 Create DTM from ROI**. Enter a name. A `.yaml` template
   is written to `rs3vision-studio/templates/dtm/` with the
   **rarest-colour** pixel in your ROI as the anchor plus 4 sample
   secondary points in a grid layout.
3. Optionally open the YAML and tune it — typical edits:
   - Tighten the anchor's `tol` so it only hits the real anvil, not
     random orange pixels.
   - Loosen secondary point `tol` if you see false negatives.
   - Delete noisy points (ones that land on constantly-changing pixels).
4. Drop a **Find DTM** block.
5. Set `template_path` to the filename (e.g. `anvil.yaml`).
6. Use its `point` output to click where it found your anchor.

**Template anatomy**:

```yaml
dtm: 1
name: anvil
anchor:
  dx: 0
  dy: 0
  color: '0x8B4513'    # the rarest colour in the ROI
  tol: 6.0             # keep tight to reduce anchor candidates
  cts: 1               # CTS1 is fastest
points:
  - dx: -20
    dy: 15
    color: '0x3C2414'  # dark grey, top-left of anvil
    tol: 12.0
    cts: 2             # CTS2 handles AA better
  - dx: 18
    dy: 22
    color: '0xC86432'  # orange hot-spot
    tol: 15.0
    cts: 2
  # ... more points
```

**Tuning cheatsheet**:

- **Anchor**: `tol` should be TIGHT (≤ 8) and `cts: 1`. You want few
  candidates for fast matching.
- **Secondary points**: `tol` can be looser (10-20) and `cts: 2`
  handles anti-aliasing better. Pick colours that are reliably present
  around the thing you're looking for.
- **3-5 points** is usually plenty. More = slower + more false
  negatives.

---

## When to use which

| Situation | Pick |
| --- | --- |
| Fixed UI icon, pixels don't change tick-to-tick | **Bitmap** |
| Element has a distinctive multi-colour pattern but its pixels vary (AA, lighting) | **DTM** |
| Need something lightning fast and the element has a unique dominant colour | **Find Color** (no bitmap / DTM needed) |
| Element has recognisable text | **Read Text** (OCR) |

**Start simple**: colour-find → DTM when colour false-positives → bitmap
when DTM is too lenient.

---

## Common pitfalls

- **Bitmap matches nothing**: tolerance too tight, or your saved PNG
  came from a different graphics setting / DPI / zoom than the current
  frame. Re-capture the PNG under the same settings you'll run under.
- **DTM matches everywhere**: anchor `tol` too high. Tighten it. Or
  your anchor colour is too common — pick a rarer one.
- **DTM matches nothing after small UI scale change**: DTM is rigid on
  offsets. If RS3's camera zoom changed, your offsets are off. Rebuild
  the template at the target zoom.
