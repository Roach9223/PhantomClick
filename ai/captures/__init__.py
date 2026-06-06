"""Cross-bot capture library.

Saved colours / snapshots / recordings can be promoted from a single
bot bundle's per-bot ``assets/`` folder to a project-wide library at
``ai/captures/global/``. Once promoted, any bot can import them by
name — particularly useful for shared signals like the Seren spirit
halo or Brooch of the Gods divine blessing proc, which appear in
every skilling bot.

Usage from a bot rule::

    from ai.captures import color, snapshot, recording

    SEREN_HALO = color("seren_spirit_halo")     # → 0xRRGGBB
    BANK_REF   = snapshot("bank_open_vip")      # → Path to PNG
    PLAYER_FISHING = recording("player_fishing")  # → Path to dir

The registry only reads the global library; per-bot bundle assets
remain accessible via :class:`ai.bot.bundle.BotBundle.asset_path`.
The Captures card in the AI tab owns the write side (Promote-to-global
button per row) and falls through to :func:`promote_color`,
:func:`promote_snapshot`, and :func:`promote_recording`.
"""

from .registry import (
    color,
    color_with_meta,
    colors,
    delete_color,
    delete_dtm,
    delete_recording,
    delete_roi,
    delete_snapshot,
    dtm,
    list_global,
    promote_color,
    promote_dtm,
    promote_recording,
    promote_roi,
    promote_snapshot,
    recording,
    roi,
    roi_with_meta,
    root,
    snapshot,
)

__all__ = [
    "color",
    "color_with_meta",
    "colors",
    "delete_color",
    "delete_dtm",
    "delete_recording",
    "delete_roi",
    "delete_snapshot",
    "dtm",
    "list_global",
    "promote_color",
    "promote_dtm",
    "promote_recording",
    "promote_roi",
    "promote_snapshot",
    "recording",
    "roi",
    "roi_with_meta",
    "root",
    "snapshot",
]
