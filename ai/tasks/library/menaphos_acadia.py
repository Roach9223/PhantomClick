"""Menaphos Acadia — full-loop Python bot.

Chops acadia trees, grabs Grace-of-the-Elves + Brooch-of-the-Gods
procs, and banks when the inventory fills up. Priority order (first
match wins each tick):

    1. Seren spirit  (GotE proc, random drop table reward)
    2. Divine blessing (Brooch proc, 4 Invention materials)
    3. Acadia tree — canopy green (primary)
    4. Acadia tree — lit trunk tan (fallback when canopy occluded)
    5. Bank when inventory full
    6. Idle fallthrough

Setup assumptions
-----------------
- **Grace of the Elves (charged)** — auto-banks acadia logs while it
  has porter charges. Default capacity 500, up to 2000 with the
  Dark Facet of Grace enchantment. 1 charge per bank event (max 5
  items per event). **When GotE runs out of charges, banking stops
  happening automatically.** At that point the bot's bank rule must
  take over — enable the ``bank_when_full`` rule and make sure the
  chest DTM is captured.
- **Brooch of the Gods** — provides the Divine Blessing proc. Does
  NOT auto-bank anything (common misconception).
- **Both** proc at 10 % / minute on the first eligible XP drop; Seren
  Spirit lasts 30 s, Divine Blessing is stationary until collected.

For an unattended overnight run:
  - Start with ~2000 GotE charges (40 Porter VIIs).
  - Keep the bank rule enabled so inventory never fills.
  - Capture a DTM of the Imperial District bank chest (colour alone
    isn't reliable — too many shared browns / blues in the scene).

Tune the colour targets with the F8 labeled-capture popup (hover each
target in-game, stack 3–5 samples, type a label, Save). Values below
are tuned from your 2026-04-21 label session.
"""

from __future__ import annotations

from ai.bot import (
    Bot,
    click,
    find_color,
    wait,
    world,
)


bot = Bot(
    name="Menaphos Acadia",
    slug="menaphos_acadia",
    tick_rate_hz=2.0,
    dry_run=True,
    # Humanizer overrides — WC-friendly feel.
    fatigue_intensity=0.30,
    break_min_clicks=60,
    break_max_clicks=110,
    break_min_duration_s=45.0,
    break_max_duration_s=180.0,
    require_foreground_window=True,
    target_window_exe="rs2client.exe",
    # AFK reliability — stop if nothing fires for 60 ticks (~30 s at 2 Hz)
    # or no click in 10 minutes.
    auto_stop_dry_ticks=60,
    watchdog_no_click_s=600.0,
    # Auto-camera — rotate the RS3 camera when detection has missed
    # for 5 ticks (~2.5 s at 2 Hz). Four 60° bursts = one full 240°
    # sweep before the watchdog kicks in. In practice usually finds
    # a tree within 1-2 bursts once camera drifts.
    auto_camera=True,
    auto_camera_dry_ticks=5,
    auto_camera_step_deg=60.0,
    auto_camera_max_bursts=4,
)


# ────────────────────────────────────────────────────────────────
# Priority 1: Grace of the Elves — Seren spirit (bright white/silver).
# ROI + min_pixels tuned so Imperial District marble doesn't false-fire.
# Verified 0 spurious matches in a fresh capture of the patch.
# ────────────────────────────────────────────────────────────────
@bot.rule(phase="collecting_boon")
def grab_seren_spirit():
    m = find_color(
        target=0xE0E8FF,
        tol=18,
        cts=2,
        min_pixels=40,         # halo is ~large; filter UI flicker
        cluster_dist=6,
        roi=TREE_ROI,
    )
    if not m:
        return False
    click.at(m.point)
    wait(1500)
    return True


# ────────────────────────────────────────────────────────────────
# Priority 2: Brooch of the Gods — divine blessing (gold).
# Gold false-positives: small acadia-tree fruits + gold UI accents.
# Tuned min_pixels up to avoid the 70-pixel tree-fruit clusters.
# ────────────────────────────────────────────────────────────────
@bot.rule(phase="collecting_boon")
def grab_divine_blessing():
    m = find_color(
        target=0xFFD200,
        tol=20,
        cts=2,
        min_pixels=120,        # orb is ~150+ px; fruits/UI typically < 90
        cluster_dist=6,
        roi=TREE_ROI,
    )
    if not m:
        return False
    click.at(m.point)
    wait(1500)
    return True


# ────────────────────────────────────────────────────────────────
# Priority 3: Chop an acadia.
#
# Two rules, in priority order:
#
# (3a) Palm-frond canopy — primary. 0x708041 is from your labeled
# capture (crop_3, note="top_view_acadia"). It's the yellow-green of
# the canopy viewed from above. Largest surface per tree, rare in
# the Imperial District palette, so false-positives are minimal.
#
# (3b) Lit trunk — fallback. 0x7A604F from your capture crop_1
# (note="acadia_tree_base") catches trees whose canopy is hidden
# behind UI overlap or off-camera. Tighter min_pixels because warm
# tans can collide with NPC sprites + chatbox.
#
# ROI excludes top HUD, right-side minimap + interface, chatbox.
# ────────────────────────────────────────────────────────────────
TREE_ROI = (100, 200, 2900, 1300)


@bot.rule(phase="chopping")
def chop_acadia_canopy():
    """Primary: palm-canopy yellow-green."""
    m = find_color(
        target=0x708041,      # your labeled "top_view_acadia"
        tol=22,
        cts=2,
        min_pixels=120,       # canopy clusters are substantial
        cluster_dist=4,
        roi=TREE_ROI,
    )
    if not m:
        return False
    click.at(m.point)
    wait(6000)
    return True


@bot.rule(phase="chopping")
def chop_acadia_trunk():
    """Fallback: lit trunk tan when canopy isn't visible."""
    m = find_color(
        target=0x7A604F,      # your labeled "acadia_tree_base"
        tol=16,               # tighter — collides with NPCs otherwise
        cts=2,
        min_pixels=60,
        cluster_dist=4,
        roi=TREE_ROI,
    )
    if not m:
        return False
    click.at(m.point)
    wait(6000)
    return True


# ────────────────────────────────────────────────────────────────
# Priority 4: Bank when the inventory is full.
#
# **Disabled by default, but genuinely needed for overnight AFK.**
# Grace of the Elves (NOT the Brooch) auto-banks Acadia logs while
# it has porter charges — default 500, max 2000. Once charges run
# out the chat spam "You transport to your bank…" stops and logs
# accumulate in inventory. This rule takes over at that point.
#
# For a true overnight run: charge GotE near full, ENABLE this rule,
# and make sure the chest DTM exists. With GotE auto-banking + this
# rule as a fallback, the bot runs indefinitely.
#
# Bank-chest detection.
#
# We sampled the chest live on 2026-04-21 and found that its light
# teal metal trim (``0xB2CBD0``) is the most distinctive pixel in the
# Menaphos Imperial District palette. A live find_color pass against
# the current scene returned 2 clusters on the chest (43 + 28 px at
# centroids (2092, 733) and (2219, 730)) and zero false positives
# outside the quest-list UI.
#
# Inventory check now uses world().inventory.count_filled() which
# parses the 4×7 grid via the awareness layer (ai/algorithms/inventory.py).
# Requires the user to run "Calibrate Inventory ROI" in the AI tab once.
# Until calibrated, the rule fires the once-per-session warning from
# WorldState and bails — the bot keeps chopping but won't bank.
BANK_CHEST_TRIM = 0xB2CBD0
BANK_SCAN_ROI = (700, 200, 2300, 1100)


@bot.rule(phase="banking", enabled=True)
def bank_when_full():
    # 26+ filled slots = "essentially full" — leaves a 2-slot buffer
    # so a stray log appearing during the bank walk doesn't prevent
    # the click. Replace with `inv.is_full()` for strict ≥28.
    inv = world().inventory
    if inv is None or inv.count_filled() < 26:
        return False
    # Find the chest by its light teal trim. min_pixels=15 catches the
    # smaller right-corner cluster; chest detection is tight enough
    # that the single largest teal cluster in the scan ROI is almost
    # always the chest.
    chest = find_color(
        target=BANK_CHEST_TRIM, tol=18, cts=2, min_pixels=15,
        cluster_dist=6, roi=BANK_SCAN_ROI,
    )
    if not chest:
        return False
    click.at(chest.point)
    wait(4000)
    return True


# ────────────────────────────────────────────────────────────────
# Priority 5: Idle fallthrough — short wait so the loop never spins.
# ────────────────────────────────────────────────────────────────
@bot.rule(phase="scanning")
def idle():
    wait(500)
    return True


if __name__ == "__main__":
    bot.run()
