# Troubleshooting

## "Visualizer stays on 'No frame yet'"

Most common: you pressed Play before adding any blocks. Check Messages
tab — if it says `graph is empty`, that's the cause. Add at least an
**On Start** block (File → New does this for you). Every new tick,
the live preview loop also pushes a frame so the visualizer should be
populated within a second of launch.

If the test frame menu item (**Run → Send test frame**) works but live
runs don't, the capture path has an issue — check Messages for
`[capture] mss detected N monitor(s)` and `[capture] first grab OK`.

## "Find Color returns nothing"

Three usual suspects, in order of likelihood:

1. **The rendered colour isn't what you think it is.** The colour you
   set in a game UI is almost never the *exact* colour that ends up on
   screen due to anti-aliasing and gamma. Use the visualizer pipette
   (click a pixel) to pick the real rendered colour.
2. **Tolerance too tight.** Start at `tol=20` for CTS2. Raise to 30+ for
   heavily anti-aliased text.
3. **Wrong monitor.** Check the Target Monitor dropdown in the toolbar.
   The preview should show what you're about to capture.

## "Script runs but no clicks fire"

Check the **Dry-run checkbox** in the toolbar. When on, every click /
move / key-press is logged instead of fired. Uncheck to enable real
input.

## "Delete / Ctrl+Z doesn't work"

The graph viewer needs keyboard focus. Click somewhere on the node
editor canvas (not a node) first. Some shortcuts also require a node
to be selected.

## "Right-click menu doesn't have Delete"

Make sure you right-clicked *on a node*, not on empty canvas. Empty
canvas gets a different (NodeGraphQt-provided) menu.

## "Bitmap matching is slow"

- Set an ROI (drag in visualizer → Use as default ROI) to narrow the
  search area.
- Raise tolerance to let the anchor prefilter cull more candidates.
- If your bitmap has a very common colour as its anchor (easy to hit
  on other parts of the screen), regenerate it at a different crop
  that includes a rarer anchor colour.

## "DTM misses valid-looking matches"

- Loosen secondary point `tol` values in the YAML.
- Remove any point that lands on a pixel that changes tick-to-tick
  (animations, particles, lighting).
- Reduce to 3-4 total points if you've overspecified.

## "Global Esc isn't stopping the script"

The kill-switch uses pynput's system-wide keyboard hook. On Windows
it should work from any app. If it doesn't:

- Check Messages for `[kill-switch] global Esc kill-switch active` at
  startup. If absent, pynput failed to install the hook (AV / group
  policy). Fall back to F6 with the Studio focused.
- Some games grab keyboard exclusively. In those cases alt-tab back to
  the Studio and press F6.

## "Template files aren't being found"

- **Bitmap**: relative paths look in `rs3vision-studio/templates/bitmap/`.
- **DTM**: relative paths look in `rs3vision-studio/templates/dtm/`.
- **Fonts**: relative paths look in the installed `rs3vision` package's
  `templates/fonts/` directory.

Use absolute paths to avoid any ambiguity.

## "My script works but the loop is too fast / too slow"

The toolbar **Tick rate** spinner controls how often the runtime walks
the graph. 5 Hz is a reasonable default. Crank to 10-20 Hz for
click-heavy scripts. Drop to 1-2 Hz when debugging so you can follow
the Block I/O tab tick by tick.
