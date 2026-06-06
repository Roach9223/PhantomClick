# Uptext detection

The RS3 NXT client draws a small action tooltip below the cursor when
hovering any interactable:

    ┌──────────────────────┐
    │ Chop down Willow     │   ← action (white) + target (yellow)
    │          +2 options  │
    └──────────────────────┘

Reading this text gives us **semantic object identity** that pixel-
level detection can't match. A single rule —
``uptext_contains: "Chop down"`` — handles every tree in the game.
Different object classes (Bankers vs Trees vs NPCs) can never collide
because the action verbs differ.

## How it works

1. The Studio's Playbook evaluator watches the live cursor position
   each tick.
2. It extracts a cursor-anchored ROI (~420 × 58 px below-right of the
   cursor) from the captured frame.
3. The cropped region goes to the rs3vision OCR engine using the
   shipped ``plain_11.rvf`` font.
4. The resulting text is split into an **action** (verb) and a
   **target** (noun) based on the yellow/white colour split.
5. Rules match against either the combined text
   (``uptext_contains: "Chop down"``) or the split form
   (``uptext: { action: "Chop down", target_regex: "^(Willow|Yew)$" }``).

## Playbook surface

Two ``when`` kinds:

**Substring / regex match:**

```yaml
- name: "Chop any tree"
  when:
    uptext_contains: "Chop down"   # case-insensitive by default
    # regex: true                  # optional — treat as Python regex
  do:
    - { click: $cursor.point }
    - { wait: 6000 }
```

**Structured match:**

```yaml
- name: "Chop willow or yew (skip magic)"
  when:
    uptext:
      action: "Chop down"
      target_regex: "^(Willow|Yew)$"
      # font_path: custom.rvf      # optional
  do:
    - { click: $cursor.point }
    - { wait: 6000 }
```

Both bind ``$cursor.point`` for the click action — the cursor is
already over the target (that's the whole point). If you want the
click to go somewhere specific, use a literal ``click: [x, y]``
instead.

## Building the font (one-time setup)

The shipped ``plain_11.rvf`` covers the default NXT render. Big UI
scale changes or Jagex font updates can break recognition; rebuild
the font from your own captures when that happens.

1. **Capture.** Launch the Studio, open any task, walk to a busy
   area in-game (a bank lobby or resource patch is good). Press
   **F9** while hovering ~20 different interactables. Each press
   drops a PNG + sidecar JSON into
   ``debug/training_frames/<date>/``.
2. **Build.** Run:

   ```
   python rs3vision-tools/build_uptext_font.py --install
   ```

   This copies every training frame into the corpus, runs
   ``extract_glyphs`` on the yellow + white ink colours, opens the
   Tk labeler (type each character shown, press Enter), then
   compiles the final ``.rvf`` and drops it in
   ``rs3vision-studio/rs3vision_studio/fonts/plain_11.rvf``.
3. **Reload.** Restart the Studio so the reader picks up the new
   font. On launch you should see *"Studio ready. …"* but **not**
   the *"uptext font not built yet"* warning.

## Tuning

If the evaluator keeps missing real uptext:

| Symptom                                  | Knob                                     |
|------------------------------------------|------------------------------------------|
| ROI doesn't include the whole tooltip    | Widen ``DEFAULT_WIDTH``/``DEFAULT_HEIGHT`` in ``rs3vision_studio/uptext.py`` |
| Misreads on yellow target words          | Rebuild font; the yellow glyphs may not be in the corpus |
| Reads action but target is garbled       | Rebuild font with more samples; ensure labeler covered lower-case letters |
| DPI / UI-scale change broke everything   | Rebuild font + retune ROI offsets        |

## MCP tool

- ``uptext_read()`` — returns the current uptext as
  ``{text, action, target, cursor_xy, confidence}``. Useful when
  Claude is chat-building a Playbook: ask the user to hover the
  target, call ``uptext_read``, paste the ``action`` into a new
  ``uptext_contains`` rule.

## Known limits

- **Playbook-only.** The graph runtime doesn't track cursor live —
  converting an uptext Playbook to a graph (escape hatch) produces
  an ``ocr.read`` with a static ROI centred on the screen, which
  will miss most hovers. Stay on Playbook for uptext work.
- **Your cursor must physically hover the thing you want to click.**
  ``$cursor.point`` clicks wherever the cursor is — the rule just
  confirms it's the right thing. Pair with a separate mouse-sweep
  helper or a human sitting at the keyboard.
- **Chat-box / other tooltips.** The ROI is cursor-anchored, so
  any tooltip under the cursor gets read. If the RS3 "examine"
  hover appears over the uptext, the reader will pick that up
  instead.
