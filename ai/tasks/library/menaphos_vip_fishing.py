"""Menaphos VIP Skilling Area — Fishing bot (CONTRAST MODE).

Catches beltfish (lvl 72) / desert sole (lvl 52) / catfish (lvl 60) at
the VIP skilling area pool. All three fish use a fishing rod + fishing
bait and spawn from the same multi-spot pool on the WEST side post-2017.

**This bot REQUIRES RS3 contrast mode.** With contrast mode on, every
interactable renders in saturated cyan and the player in red — colour
detection becomes trivially reliable and the bot drops the complex
animation / DTM machinery the prior version needed.

Loop overview (priority order, first match wins each tick):

    1. preflight — fail-fast if required captures aren't promoted.
    2. bank_preset_when_chest_open — bank UI is up → press 1 to load preset.
    3. walk_to_bank_when_full — inv full → cyan match in CHEST_ROI →
       hover-verify (optional) → click.
    4. recast_when_idle — player not animating + cyan spot in POOL_ROI →
       hover → verify tooltip snapshot → click.fire().
    5. idle_fallthrough — wait 500 ms.

Setup checklist
---------------

In-game:
    • Menaphos favour high enough for VIP access.
    • **Enable contrast mode** (Options → Graphics → High contrast).
    • Fishing rod + bait equipped/inventoried.
    • Save Preset 1 (Banking → Presets) = empty inv + N bait. Verify
      manually that pressing ``1`` at the chest swaps the inv AND
      auto-closes the bank.
    • Stand on the WEST side of the pool. Lock the camera.
    • ``key_input_method = "serial_hid"`` configured (NXT filters
      every other keystroke path).

In the AI tab → pick a bundle → take + ★ Promote each:

    color        contrast_cyan        ← 3-5 clicks on cyan interactables
                                        (trees, fruits, the fishing pool
                                        itself). Used by find_interactable.
    color        contrast_red         ← 3-5 clicks on your red player.
                                        Used by find_player.
    snapshot     bank_open_vip        ← bank UI fully open (full screen)
    snapshot     vip_spot_tooltip     ← hover the fishing spot in-game
                                        so the "Bait fishing spot" tooltip
                                        shows, then capture just the
                                        tooltip text (use F9 hover-snapshot)
    ROI          vip_pool_west        ← rect over west half of the pool
    ROI          vip_chest_search     ← rect that frames the bank chest

The hover→tooltip-verify→click pattern: every click waits ~300 ms for
the RS3 tooltip to appear, template-matches it against the saved
tooltip snapshot, and only fires if the match clears the threshold.
No OCR dependency.
"""

from __future__ import annotations

from ai.bot import (
    Bot,
    click,
    find_interactable,
    is_bank_open,
    key,
    log,
    move,
    player_is_animating,
    stop,
    template_match,
    tooltip_match,
    wait,
    world,
)
from ai.captures import colors, roi, snapshot


# ─────────────────────────────────────────────────────────────────
# Captures resolved from the global library.
#
# Search ROIs (POOL_ROI, POOL_ROI_WIDE, CHEST_ROI) are saved via the
# Captures card's 📍 Search ROI button — drag the rect once, the bot
# loads the rect from JSON. No more pasting tuples into this file.
#
# Player animation has no separate ROI — it's stored in the
# player_fishing recording's meta.json and read by
# is_animating_recording.
#
# Each capture is independent — missing ones get listed by the
# preflight rule and the bot stops with one clear log line instead
# of a stack trace mid-tick.
# ─────────────────────────────────────────────────────────────────


_MISSING: list[str] = []


def _try_colors(name: str):
    try:
        return colors(name)
    except KeyError:
        _MISSING.append(f"colour {name!r}")
        return None


def _try_snapshot(name: str):
    try:
        return snapshot(name)
    except KeyError:
        _MISSING.append(f"snapshot {name!r}")
        return None


def _try_roi(name: str):
    try:
        return roi(name)
    except KeyError:
        _MISSING.append(f"ROI {name!r}")
        return None


# Search ROIs — captured via 📍 Search ROI button.
POOL_ROI = _try_roi("vip_pool_west")          # cyan-search area for the pool
CHEST_ROI = _try_roi("vip_chest_search")      # cyan-search area for the chest


# Contrast-mode palette — captured once via the Colour label tool and
# promoted globally so every skilling bot inherits the detection. The
# bot framework's find_interactable() / find_player() resolve these
# slugs automatically; we trigger the same _MISSING tracking here so
# the preflight rule surfaces the missing capture cleanly instead of
# leaving the bot mute mid-tick.
CYAN_SAMPLES = _try_colors("contrast_cyan")
RED_SAMPLES = _try_colors("contrast_red")

# Snapshot reference for the bank UI being open.
BANK_OPEN_REF = _try_snapshot("bank_open_vip")

# Tooltip snapshots — optional cursor-anchored verification. Loaded
# silently (NOT in _MISSING); when present, rules require the tooltip
# to template-match before clicking. When absent, the cyan match
# alone drives the click.
def _opt_snapshot(name: str):
    try:
        return snapshot(name)
    except KeyError:
        return None

SPOT_TOOLTIP = _opt_snapshot("vip_spot_tooltip")          # "Bait fishing spot"
CHEST_TOOLTIP = _opt_snapshot("vip_chest_tooltip")        # "Bank chest"

# Optional: in-game popup that RS3 shows when inventory is full.
# When present, the bank rule fires on EITHER inventory count >= 27
# OR this template matching above threshold. Useful as a redundant
# signal — and as the only signal when inventory ROI isn't calibrated.
#
# Capture-quality warning: the template needs to clearly contain the
# RED "Your inventory is too full" chat text. A capture of empty
# chatbox chrome (dark title bar + beige interior, no text) will
# match constantly and trigger false-positive bank trips. If your
# inventory ROI is calibrated, you can skip this entirely — the
# count_filled() >= 27 check is already reliable.
INV_FULL_REF = _opt_snapshot("inv_full")


bot = Bot(
    name="Menaphos — VIP Fishing",
    slug="menaphos_vip_fishing",
    tick_rate_hz=2.0,
    dry_run=True,
    fatigue_intensity=0.25,
    break_min_clicks=70,
    break_max_clicks=130,
    break_min_duration_s=40.0,
    break_max_duration_s=160.0,
    require_foreground_window=True,
    target_window_exe="rs2client.exe",
    # Bait running out manifests as "click spot, no animation, repeat".
    # The watchdog catches it after 10 minutes so the bot doesn't
    # spam-click forever.
    auto_stop_dry_ticks=120,            # 60 s @ 2 Hz
    watchdog_no_click_s=600.0,
    # Camera is fixed in the VIP area — auto-camera off so we don't
    # accidentally rotate out of the captured ROIs.
    auto_camera=False,
)


# Idle-grace counter — the spot relocates at half rate, so a 1-tick
# "not animating" reading is normal between catches. Wait 3 ticks of
# silence before treating idle as real and re-clicking.
_idle_ticks = {"n": 0}


# ─────────────────────────────────────────────────────────────────
# Priority 1: preflight — make the missing-capture failure obvious.
# Fires exactly once at start, stops the bot with a clear error.
# ─────────────────────────────────────────────────────────────────
@bot.rule(phase="scanning")
def preflight():
    if not _MISSING:
        return False
    log(
        "[menaphos_vip_fishing] missing global captures: "
        + ", ".join(_MISSING)
    )
    log(
        "Open AI tab → Captures card on any bundle → take the missing "
        "captures (see the .task.yaml setup notes) → ★ Promote each "
        "one to global. Then restart this bot."
    )
    stop("missing required captures — see log")
    return True


# ─────────────────────────────────────────────────────────────────
# Priority 2: bank UI is open → press 1 to load the preset.
# Bank closes on preset load, so next tick we're back to fishing.
# ─────────────────────────────────────────────────────────────────
@bot.rule(phase="banking")
def bank_preset_when_chest_open():
    if BANK_OPEN_REF is None:
        return False
    if not is_bank_open(BANK_OPEN_REF, threshold=0.85):
        return False
    log("bank open — loading preset 1")
    key("1")
    wait(1500)                          # preset swap animation
    return True


# ─────────────────────────────────────────────────────────────────
# Priority 3: inventory full → cyan match in CHEST_ROI → click.
#
# With contrast mode on, the bank chest renders the same saturated
# cyan as every other interactable. ``find_interactable`` is a thin
# wrapper around find_any_color(contrast_cyan_samples). The
# hover→tooltip-verify→fire pattern still gates the click.
# ─────────────────────────────────────────────────────────────────
@bot.rule(phase="banking")
def walk_to_bank_when_full():
    # TWO independent signals can trigger banking — either is enough:
    #   • count_says_full: the inventory ROI scan reports ≥ 27 filled
    #     slots. Requires "Calibrate Inventory ROI" to have been run.
    #   • popup_says_full: RS3's "your inventory is too full" chatbox
    #     popup is currently template-matching above threshold. Works
    #     even without inventory calibration; also catches edge cases
    #     where the slot count was misread.
    inv = world().inventory
    count_says_full = inv is not None and inv.count_filled() >= 27
    popup_says_full = (
        INV_FULL_REF is not None
        and bool(template_match(INV_FULL_REF, threshold=0.85))
    )
    if not (count_says_full or popup_says_full):
        return False
    chest = find_interactable(roi=CHEST_ROI, min_pixels=20)
    if not chest:
        return False
    reason = []
    if count_says_full:
        reason.append("count")
    if popup_says_full:
        reason.append("popup")
    log(
        f"inv full ({'+'.join(reason)}) — moving to bank chest "
        f"(cyan match, {chest.count}px)"
    )
    move(chest.point)
    wait(300)                           # tooltip latency
    if CHEST_TOOLTIP is not None:
        if not tooltip_match(CHEST_TOOLTIP, threshold=0.7):
            return False                # cursor isn't on the chest; retry
    click.fire()
    wait(2500)                          # auto-walk + bank open animation
    return True


# ─────────────────────────────────────────────────────────────────
# Priority 4: recast when player isn't animating.
#
# Detection in contrast mode:
#   • player_is_animating() tracks the red blob's centroid + pixel
#     count over a sliding window. Walking moves the centroid;
#     rod-swing animation cycles the bbox → pixel count fluctuates.
#     Both register as "animating".
#   • find_interactable(POOL_ROI) returns the largest cyan cluster
#     centroid — the fishing spot is the only cyan thing inside the
#     pool ROI, so this is unambiguous.
# ─────────────────────────────────────────────────────────────────
@bot.rule(phase="fishing")
def recast_when_idle():
    inv = world().inventory
    if inv is not None and inv.count_filled() >= 27:
        return False                    # bank rule should fire instead
    if POOL_ROI is None:
        return False
    if player_is_animating():
        _idle_ticks["n"] = 0
        return False
    _idle_ticks["n"] += 1
    if _idle_ticks["n"] < 3:
        return False                    # grace; spot may relocate any tick
    # debug_label="recast" instruments find_any_color so each sample's
    # pixel count + chosen centroid is logged. Use the log table in
    # gameplan.md to map the output to one of four failure modes.
    spot = find_interactable(roi=POOL_ROI, min_pixels=20, debug_label="recast")
    if not spot:
        return False                    # no cyan in pool ROI yet
    move(spot.point)
    wait(300)                           # in-game tooltip latency
    if SPOT_TOOLTIP is not None:
        match = tooltip_match(SPOT_TOOLTIP, threshold=0.7)
        if not match:
            return False                # cursor isn't over the spot; retry
        log(
            f"recasting — cyan centroid={spot.point} "
            f"px={spot.count} tooltip_conf={match.confidence:.2f}"
        )
    else:
        log(f"recasting — cyan centroid={spot.point} px={spot.count} (no tooltip ref)")
    click.fire()
    _idle_ticks["n"] = 0
    wait(1500)                          # fishing animation start
    return True


# ─────────────────────────────────────────────────────────────────
# Priority 5: idle fallthrough so the loop never spins hot.
# ─────────────────────────────────────────────────────────────────
@bot.rule(phase="scanning")
def idle():
    wait(500)
    return True


if __name__ == "__main__":
    bot.run()
