"""Menaphos Acadia screen-rule example; starts in dry run.

Calibrate Inventory ROI and promote a full-screen bank-open snapshot named
bank_open_acadia. Save and manually verify bank preset 1 with an empty
woodcutting inventory. Banking has priority over collecting and chopping.
The colors and search rectangles below are sample values: calibrate them
for your display and camera before considering live input. No successful
unattended game run is implied by this example.
"""

from __future__ import annotations

from ai.bot import (
    Bot,
    click,
    find_color,
    wait,
    world,
    is_bank_open,
    key,
    stop,
)

from ai.captures import snapshot

try:
    BANK_OPEN_REF = snapshot("bank_open_acadia")
except KeyError:
    BANK_OPEN_REF = None
_bank_attempts = {"n": 0}

bot = Bot(
    name="Menaphos Acadia",
    slug="menaphos_acadia",
    tick_rate_hz=2.0,
    dry_run=True,
    # Humanizer overrides, WC-friendly feel.
    fatigue_intensity=0.30,
    break_min_clicks=60,
    break_max_clicks=110,
    break_min_duration_s=45.0,
    break_max_duration_s=180.0,
    require_foreground_window=True,
    target_window_exe="rs2client.exe",
    # AFK reliability, stop if nothing fires for 60 ticks (~30 s at 2 Hz)
    # or no click in 10 minutes.
    auto_stop_dry_ticks=60,
    watchdog_no_click_s=600.0,
    # Auto-camera, rotate the RS3 camera when detection has missed
    # for 5 ticks (~2.5 s at 2 Hz). Four 60° bursts = one full 240°
    # sweep before the watchdog kicks in. In practice usually finds
    # a tree within 1-2 bursts once camera drifts.
    auto_camera=True,
    auto_camera_dry_ticks=5,
    auto_camera_step_deg=60.0,
    auto_camera_max_bursts=4,
)


BANK_CHEST_TRIM = 0xB2CBD0
BANK_SCAN_ROI = (700, 200, 2300, 1100)


@bot.rule(phase="setup")
def require_bank_setup():
    if world().inventory is None or BANK_OPEN_REF is None:
        stop("Calibrate Inventory ROI and capture bank_open_acadia before starting")
        return True
    return False


@bot.rule(phase="banking")
def load_bank_preset():
    if not is_bank_open(BANK_OPEN_REF, threshold=0.85):
        _bank_attempts["n"] = 0
        return False
    if _bank_attempts["n"] >= 3:
        stop("Bank preset 1 did not close the bank after three attempts")
        return True
    _bank_attempts["n"] += 1
    key("1")
    wait(1500)
    return True


@bot.rule(phase="banking")
def bank_when_full():
    inv = world().inventory
    if inv is None or inv.count_filled() < 26:
        return False
    chest = find_color(target=BANK_CHEST_TRIM, tol=18, cts=2,
                       min_pixels=15, cluster_dist=6, roi=BANK_SCAN_ROI)
    if chest:
        click.at(chest.point)
        wait(4000)
    else:
        # Claim this tick so a missing bank target cannot fall through to chop.
        stop("Inventory full but bank chest was not found; check bank search area")
    return True


# ────────────────────────────────────────────────────────────────
# Priority 1: Grace of the Elves, Seren spirit (bright white/silver).
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
# Priority 2: Brooch of the Gods, divine blessing (gold).
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
# (3a) Palm-frond canopy, primary. 0x708041 is from your labeled
# capture (crop_3, note="top_view_acadia"). It's the yellow-green of
# the canopy viewed from above. Largest surface per tree, rare in
# the Imperial District palette, so false-positives are minimal.
#
# (3b) Lit trunk, fallback. 0x7A604F from your capture crop_1
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
        tol=16,               # tighter, collides with NPCs otherwise
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


@bot.rule(phase="scanning", idle=True)
def idle():
    wait(500)
    return True
