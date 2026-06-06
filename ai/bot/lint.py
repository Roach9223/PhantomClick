"""Pre-run sanity check for bot bundles.

Walks a :class:`BotProgram` against its bundle and returns a list of
plain-language issues the user should know about before pressing
Start. The App surfaces these as a toast + console dump and lets the
user choose to start anyway (incremental authoring may legitimately
have unfinished steps).

The lint covers what the runner's compile errors miss: things that
won't trip a step's per-step validator but will silently produce
worse-than-expected runtime behaviour. Examples:

- A step references a snapshot that doesn't exist on disk
- An interrupt handler points at a procedure that was deleted
- Inventory ROI isn't calibrated but a step uses ``if_inventory_full``
- Minimap isn't calibrated but ``on_player_moved_unexpectedly`` is wired

All checks are read-only, run on the user's machine, and complete in
well under a second. Designed to be the friendly "your bot is ready /
N issues" toast that prevents 80% of "I started it and it just sat
there" first-runs.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .authoring import (
    AIBotStep, KIND_FIND_CAPTURE_CLICK, KIND_FIND_COLOR_CLICK,
    KIND_FIND_COLOR_KEY, KIND_FIND_DTM_CLICK, KIND_FIND_ANIMATION_CLICK,
    KIND_IF_HP_BELOW, KIND_IF_INVENTORY_FULL, KIND_IF_ITEM_COUNT,
    KIND_KEY_PRESS, KIND_LABELS, KIND_LOOP_BACK, KIND_UPTEXT_CHECK,
    KIND_WAIT, KIND_ZONE_CLICK, deserialize_steps,
)
from .procedures import (
    BotProgram, Procedure, HANDLER_ABORT,
    TRIGGER_IF_HP_BELOW, TRIGGER_IF_INVENTORY_FULL, TRIGGER_IF_ITEM_COUNT,
    TRIGGER_ON_CHAT, TRIGGER_ON_PLAYER_MOVED, TRIGGER_ON_UPTEXT,
)


def lint_bundle(bundle: Any, program: BotProgram) -> List[str]:
    """Return a list of issue messages (empty list = bot is ready).

    ``bundle`` may be None (legacy / library bot path) — in that case
    bundle-asset checks are skipped and only program-level issues
    surface.
    """
    issues: List[str] = []
    if not program.procedures:
        issues.append("Program has no procedures.")
        return issues

    # Build a set of valid handler targets — procedure names + 'abort'.
    valid_handlers = set(program.procedures.keys()) | {HANDLER_ABORT}

    # Index every step's kind across all procedures so we can decide
    # which ROI calibrations are required.
    all_kinds: set[str] = set()
    uses_inventory: bool = False
    uses_bars: bool = False
    uses_minimap: bool = False
    uses_uptext: bool = False

    # Walk procedures.
    for proc_name, proc in program.procedures.items():
        if not isinstance(proc, Procedure):
            issues.append(f"Procedure {proc_name!r} is malformed.")
            continue
        ai_steps = deserialize_steps(proc.steps)
        if not ai_steps:
            issues.append(
                f"Procedure {proc_name!r} has no enabled steps."
            )
            continue
        for i, step in enumerate(ai_steps):
            all_kinds.add(step.kind)
            label = (
                f"{proc_name}/{i + 1} ({KIND_LABELS.get(step.kind, step.kind)})"
            )
            issues.extend(_lint_step(step, label, bundle))
            if step.kind in (KIND_IF_INVENTORY_FULL, KIND_IF_ITEM_COUNT):
                uses_inventory = True
            if step.kind == KIND_IF_HP_BELOW:
                uses_bars = True
            if step.kind == KIND_UPTEXT_CHECK:
                uses_uptext = True
            # Verify spec → uptext / chat readers
            spec = step.verify or {}
            sig = str(spec.get("signal") or "")
            if sig == "uptext_match":
                uses_uptext = True

    # Walk interrupts.
    for intr in program.interrupts:
        label = f"interrupt {intr.name!r}"
        if not intr.enabled:
            continue
        if intr.handler not in valid_handlers:
            issues.append(
                f"{label}: handler {intr.handler!r} is not a procedure name "
                f"and not 'abort'."
            )
        if intr.trigger == TRIGGER_IF_INVENTORY_FULL:
            uses_inventory = True
        elif intr.trigger == TRIGGER_IF_HP_BELOW:
            uses_bars = True
        elif intr.trigger == TRIGGER_IF_ITEM_COUNT:
            uses_inventory = True
            name = str((intr.params or {}).get("item_name") or "").strip()
            if not name:
                issues.append(f"{label}: item_name is empty.")
        elif intr.trigger == TRIGGER_ON_PLAYER_MOVED:
            uses_minimap = True
        elif intr.trigger == TRIGGER_ON_UPTEXT:
            uses_uptext = True
        elif intr.trigger == TRIGGER_ON_CHAT:
            pat = str((intr.params or {}).get("match") or "").strip()
            if not pat:
                issues.append(f"{label}: chat-match pattern is empty.")

    # Calibration checks — only if the corresponding feature is used.
    if bundle is not None:
        cal = bundle.calibration or {}
        if uses_inventory and not cal.get("inventory_rect"):
            issues.append(
                "Inventory ROI not calibrated — run 'Calibrate Inventory ROI' "
                "in the AI tab. Required by inventory predicates."
            )
        if uses_bars and not (cal.get("bars_rect") or cal.get("orbs_rect")):
            issues.append(
                "Bars ROI not calibrated — run 'Calibrate Bars ROI' at 100% "
                "HP/Adren/Prayer/Sum. Required by HP-below interrupts."
            )
        if uses_minimap and not cal.get("minimap_rect"):
            issues.append(
                "Minimap ROI not calibrated — run 'Calibrate Minimap ROI' at "
                "100% run-energy. Required by on_player_moved + run_energy_pct."
            )

    # Item-library checks — gather distinct item names referenced.
    referenced_items: set[str] = set()
    for proc in program.procedures.values():
        if not isinstance(proc, Procedure):
            continue
        for step in deserialize_steps(proc.steps):
            if step.kind == KIND_IF_ITEM_COUNT and step.item_name.strip():
                referenced_items.add(step.item_name.strip())
    for intr in program.interrupts:
        if intr.enabled and intr.trigger == TRIGGER_IF_ITEM_COUNT:
            nm = str((intr.params or {}).get("item_name") or "").strip()
            if nm:
                referenced_items.add(nm)
    if referenced_items and bundle is not None:
        present = {p.stem for p in bundle.list_items()}
        missing = sorted(
            n for n in referenced_items if _slugify(n) not in present
        )
        if missing:
            issues.append(
                "Items referenced but not in the library yet: "
                + ", ".join(repr(n) for n in missing)
                + ".  Add via the Items panel (auto-fetches from the wiki)."
            )

    return issues


def _lint_step(step: AIBotStep, label: str, bundle: Any) -> List[str]:
    """Return any issues specific to a single step."""
    issues: List[str] = []
    kind = step.kind

    if kind == KIND_FIND_CAPTURE_CLICK:
        name = (step.capture_name or "").strip()
        if not name:
            issues.append(f"{label}: capture_name is empty.")
        elif bundle is not None:
            try:
                p = bundle.asset_path(name, "snapshot")
            except Exception:
                p = None
            if p is None:
                issues.append(
                    f"{label}: snapshot {name!r} not on disk. "
                    f"Capture it via the Captures section."
                )

    if kind == KIND_ZONE_CLICK:
        if not step.zone_json:
            issues.append(f"{label}: zone not drawn.")

    if kind == KIND_FIND_COLOR_CLICK or kind == KIND_FIND_COLOR_KEY:
        if step.color_target_rgb is None:
            issues.append(f"{label}: no colour picked.")
        if int(step.color_min_pixels) <= 0:
            issues.append(f"{label}: color_min_pixels must be > 0.")
        if kind == KIND_FIND_COLOR_KEY and not step.key_combo.strip():
            issues.append(f"{label}: key_combo is empty.")

    if kind == KIND_FIND_DTM_CLICK:
        if not (step.dtm_template_path or "").strip():
            issues.append(f"{label}: dtm_template_path is empty.")

    if kind == KIND_FIND_ANIMATION_CLICK:
        if step.roi is None:
            issues.append(
                f"{label}: animation needs an ROI (Set ROI in the editor)."
            )

    if kind == KIND_KEY_PRESS:
        if not step.key_combo.strip():
            issues.append(f"{label}: key_combo is empty.")
        else:
            try:
                from modules.key_timer import parse_combo
                parse_combo(step.key_combo)
            except Exception as e:
                issues.append(f"{label}: key combo {step.key_combo!r} unparsable ({e}).")

    if kind == KIND_LOOP_BACK:
        if step.loop_count and step.loop_count < 0:
            issues.append(f"{label}: loop_count must be ≥ 0.")

    if kind == KIND_UPTEXT_CHECK:
        if not step.uptext_pattern.strip():
            issues.append(f"{label}: uptext_pattern is empty.")

    return issues


def _slugify(name: str) -> str:
    """Match the wiki client's slugify so item-name lookups align."""
    import re
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unknown"
