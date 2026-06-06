# Menaphos — Acadia Trees (full loop)

Two implementations of the same task:

| Version   | Slug                        | Implementation                                            | Lines of YAML |
|-----------|-----------------------------|-----------------------------------------------------------|---------------|
| **Playbook** (recommended) | `menaphos_acadia_full_pb` | `tasks/library/menaphos_acadia_full.playbook.yaml` (5 plays)  | ~55 |
| Graph     | `menaphos_acadia_full`      | `recipes/acadia_menaphos.rvscript` (21 nodes, 30 edges)  | ~170 |

The Playbook reads top-to-bottom like English ("grab Seren spirit;
else grab divine blessing; else chop acadia; else bank when full;
else idle") and doesn't require wiring `capture.frame` into five
separate detector ports. Pick the Playbook version unless you
specifically need parallel branches or the node-graph escape hatch.

Both versions share the same colour targets, DTM, humanizer
overrides, and tuning checklist below. Claude can build the Playbook
version from scratch via MCP in a few minutes — see
`docs/playbook-mcp-flow.md`.

Task slug (graph): `menaphos_acadia_full`
Recipe: `recipes/acadia_menaphos.rvscript`

## What it does

Full-loop woodcutter for Menaphos Imperial District's Acadia patch
with priority-ordered interrupts for the two skilling-outfit procs:

| Priority | Branch             | Fires when                                   | Action                       |
|----------|--------------------|----------------------------------------------|------------------------------|
| 1        | Seren spirit       | Grace of the Elves spawns a helper sprite    | Click it, 1.5 s settle       |
| 2        | Divine blessing    | Brooch of the Gods drops a proc orb          | Click it, 1.5 s settle       |
| 3        | Acadia tree        | A brown trunk cluster is visible on-screen   | Click, 6 s chop              |
| 4        | Inventory full     | Log-colour cluster in inventory ≥ threshold  | DTM-click bank chest, 4 s    |
| —        | Fallthrough        | Nothing matched this tick                    | 500 ms wait                  |

Each tick of the runtime walks the graph once. Because branches chain
via `if_else.false`, only one action fires per tick — so the seren
spirit always wins over a tree even if both are on screen.

## Before you hit Play

1. **Equip the outfit.** The procs will never spawn if you don't have
   Brooch of the Gods + Grace of the Elves equipped. Check charges —
   both deplete with use.

2. **Graphics.** Low-to-medium detail, top-down camera. Flat-shaded
   trunks match tolerances much better than full lighting.

3. **Tune the four colours** with the Visualizer pipette (click any
   pixel → hex is copied + applied to the selected `Find Color` node):
   - `n3` — Seren spirit halo (pure-white glow)
   - `n7` — Divine blessing orb (gold)
   - `n11` — Acadia trunk (dark brown)
   - `n15` — Acadia log (inventory brown)

4. **Set the inventory ROI.** Drag a rect around the inventory panel
   on the visualizer → paste the coords into `n15.roi` (e.g.
   `"2500,900,360,520"`).

5. **Capture the bank-chest DTM.** Drag a tight ROI around one bank
   chest pillar → 🎯 Create DTM from ROI → save as
   `menaphos_imperial_bank_chest.yaml`. The recipe already points at
   that filename.

6. **Dry-run first.** With 🧪 toggled ON, press F5. Watch the log:
   every branch logs "found / not found" every tick. Tune `tol` and
   `min_cluster_size` until only the right branch fires at the right
   time.

## Tuning knobs

Values in `params:` of the task YAML override Studio defaults for
humanization. The woodcutting-specific tweaks:

| Param                    | Value | Why                                    |
|--------------------------|-------|----------------------------------------|
| `fatigue_intensity`      | 0.3   | Long WC sessions → more drift          |
| `break_min_clicks`       | 60    | Fewer short breaks (WC is slow)        |
| `break_max_clicks`       | 110   |                                        |
| `break_min_duration_s`   | 45    | Short breaks feel synthetic; go longer |
| `break_max_duration_s`   | 180   |                                        |
| `require_foreground_window` | true | Safety — won't click if you alt-tab  |

## Known gaps (not yet wired)

- No world-hop / camera-rotate if the patch is empty. If no tree is
  visible for many ticks, the script stays in `scanning` forever.
- No recharge logic for Brooch / GotE — when they run out of charges
  procs stop but the script doesn't flag it.
- No VIP bank support (that's a deliberate `menaphos_acadia_vip`
  follow-up task).
- Inventory-full check is pixel-count-based. Works reliably for
  acadia logs but doesn't count bird nests / divine boons — those
  sit in the inventory but don't trigger bank.

## Claude / MCP integration tips

Once the task is active and the Studio's MCP toggle is ON, Claude
can call:

- `task_phase()` → watches which branch is currently firing.
- `task_health()` → click / detection / failure counters.
- `set_task_param("fatigue_intensity", 0.45)` → live-tune without
  restarting.
- `graph_ids()` + `set_param()` → e.g. bump `n11.tol` if the user
  says "trees aren't matching reliably".

A good Claude prompt while tuning: *"Watch the phase for 30 s,
then tell me if any branch is stuck or misfiring."* — Claude can
poll `task_phase()` + `task_health()` and report.
