# PhantomClick — design system audit

## Top-line

Compliance is roughly **75% across the app**. No critical breaks, no information-architecture problems, no tab needs a rethink. The work that remains splits cleanly into:

- **One global token fix** (1-line change in `qss.py:224-227`) that flips every "form-row" tab's section eyebrow from grey to teal — fixes Behavior / Hotkeys / Timers / Stats / Settings simultaneously.
- **One small refactor** (Monitor): hand-rolled `QHBoxLayout` rows should migrate to `SettingsRow` for consistency with the rest of the form-row family.
- **One de-duplication**: `_screen_label()` is copy-pasted in `monitor.py` and `settings.py`. Extract to `ui/format.py` or a new `ui/screen_utils.py`.
- **Polish**: unit-formatting consistency, mono-font on the Stats card, a few teal-usage exceptions to document or fix.

The Record tab redesign established two patterns that the rest of the app now needs to align with — but they're orthogonal patterns, not one canonical pattern:

- **Card-based mode pages** (Click, Record, AI): Card → Section → Field → action row. Uses `Section` widget (teal eyebrow), `Card`, `Expander`, the new step-card active stripe.
- **Form-row settings pages** (Hover, Behavior, Hotkeys, Timers, Stats, Settings): `GroupHeader` → `SettingsGroup` → `SettingsRow`. Tighter rhythm, flatter hierarchy, no cards.

Both are legitimate. The audit's main recommendation is **document the split** so future tabs pick the right one without re-deriving it, and fix the cosmetic gaps within each lane.

---

## Established design patterns (reference)

**Layout**

- 8 px grid: 24 px between sections, 12 px between fields within a section, 8 px micro-rows.
- Section labels in small uppercase teal (~11–12 px / 700 / letter-spacing 1.4 px).
- No hairline rules trailing section labels — typography carries the hierarchy.
- 2-column grids where fields are conceptually paired; single-column when independent.

**Typography (3 sizes only)**

- Large bold (titles, primary CTAs).
- Medium regular (body, inputs) — 13 px field labels semibold, 14 px body.
- Small caption (hints, captions, tertiary state) — 12 px tertiary.
- Mono font for numerical data and coordinates.
- Italic + tertiary for collapsed-state metadata.
- Tabular-nums for numeric grids.

**Color discipline (TEAL #22d3ee)**

- Teal IS for: primary CTAs only, section labels, active-state stripes (3 px left edge), slider thumbs/tracks.
- Teal NOT for: secondary buttons, toggles when on (desaturated blue-grey instead), informational chrome.

**Component rules**

- Action buttons get NO chevron prefix.
- Disclosure toggles: `▸  **Advanced**  shape, button, mode` (chevron grey, label primary-bold, preview muted-tertiary, comma-separated).
- Active expanded cards in a list: 3 px teal left stripe; collapsed ones: transparent stripe (geometry preserved).
- Collapsed cards must show identifying state (label OR fallback to coords/values) in tertiary mono italic.
- Destructive actions visually distinct from safe ones.
- Empty states: single prominent teal CTA, not a paragraph of help.

**Unit formatting**

- Time: always seconds with 3-decimal precision (`0.932 s`); driven by `ui/format.py::fmt_delay`.
- Coordinates: `(X, Y)` with space after comma.
- Dimensions: `WxH px`.
- Percentages: integer `%` unless precision matters.

---

## Tab: Click

**Current state.** Single-zone clicker config — zone picker + timing + realism stub, in two responsive cards (stack on narrow, side-by-side ≥1200 px). Card-based, uses `SectionLabel` eyebrows inside each card.

**Compliance.** ✅ Section eyebrows (compliant since they use `SectionLabel` already), ✅ no hairlines, ✅ teal discipline, ✅ unit formatting via `fmt_delay`, ✅ mono for numerics, ✅ destructive vs safe (Clear is secondary, Redraw is primary teal). ⚠️ Three-tier typography: card headers render at 10 px which is below the 13 px field-label spec, but this matches the deliberate "card title quieter than page title" decision documented in `qss.py:78-82` so probably keep.

**Complexity.** SMALL (cosmetic only).

**Specific changes.**

- `ui/cards/click_mode.py:287-292` — the spacing-rhythm divider is fine but add a comment noting it's a typographic break, not a section rule, so future readers don't think it's a stale hairline. `[safe]`
- Verify `SegmentedControl` "Button" / "Pattern" rows don't over-saturate their selected pill in teal — agent confirms current behavior is correct, just worth a visual once-over. `[safe]`

**Dependencies.** Uses `Card`, `SectionLabel`, `SegmentedControl`, `RangeSpinSlider`, `IntervalDisplay`, `PresetCard`, `StatePill`, `ZonePreview`. Shares with Record tab (`SectionLabel`, `RangeSpinSlider`) and Hover (`SegmentedControl`). Does not use `Section` (Click was deliberately flattened — only `SectionLabel`).

---

## Tab: Record (reference — already shipped)

Already redesigned. Use as the canonical pattern for the card-based mode tabs.

---

## Tab: AI

**Current state.** Five vertically stacked Cards: Hero (bot picker + goal + phase chips), Live (status pills + stat chips + frame thumb), Rules (rule list with active highlight), Config (tick rate / monitor / dry-run / advanced expander), Log (segmented filter + colored output).

**Compliance.** ✅ Mostly compliant — three-tier typography, mono numerics, unit formatting, no hairlines, teal restraint, action-button chevron rule, destructive vs safe. ⚠️ The "Show setup notes" toggle in the Hero is a custom `QPushButton` with chevron text — should reuse the `Expander` widget (the Config section's "Advanced" disclosure already does it correctly). ⚠️ Card-internal spacing varies (some 4 px, some 6 px, some 8 px) and should normalize to 12 px field-gap rhythm.

**Complexity.** MEDIUM (structural — one widget swap + spacing cleanup).

**Specific changes.**

- `ui/cards/ai.py:386-402` — replace the setup-notes toggle (custom `QPushButton` with chevron text) with an `Expander` instance for consistency with the Advanced disclosure at line 717. `[risky — refactor]`
- `ui/cards/ai.py:379-383` — normalize the phase-chips row's `setContentsMargins(0, 4, 0, 0)` → `(0, t.SP_SM, 0, 0)`. `[safe]`
- `ui/cards/ai.py:522-540` — stat-chip grid contentsMargins `(0, 4, 0, 4)` → `(0, t.SP_SM, 0, t.SP_SM)`. `[safe]`
- Bot dropdown selection-bg uses `ACCENT_DIM_FALLBACK` (solid hex) — switch to `ACCENT_DIM` (rgba) if Qt's combo popup supports it. `[safe]`

**Dependencies.** `Card`, `StatusDot`, `SegmentedControl`, `LabeledSlider`, `IOSSwitch`, `Expander`. Custom internal: `_PhaseChip`, `_StatChip`, `_RuleRow`, `_PreviewThumb`. The `_StatChip` is **not** unified with Stats tab's bare mono labels — agents recommend keeping them split (different contexts: dashboard vs. live bot telemetry).

---

## Tab: Hover

**Current state.** Form-row layout. Two `SettingsGroup`s: "Zones" (per-row thumbnails + kind label + delete + empty-state CTA) and "Visits" (master switch + frequency + dwell range + selection mode).

**Compliance.** ✅ Most compliant of all the form-row tabs. 8 px grid is clean, mono numerics on coordinate readouts ("r=50 at (125, 200)"), teal restraint correct (`QuietAccentButton` for `+ Add zone`, `BorderlessButton` for shape menu, icon-danger red for delete), empty-state CTA pops correctly. ✅ `(125, 200)` coords use the canonical "space after comma" format. Uses × (multiply sign) for dimensions ("100 × 200") which is consistent.

**Complexity.** SMALL (cosmetic only).

**Specific changes.**

- `ui/cards/hover_zones.py:291-303` — confirm `ZoneThumbnail` and `SettingsRow.leading=thumb` align without orphan space. `[safe]`
- Confirm delete buttons render at consistent 28×24 px across all rows. `[safe]`

**Dependencies.** `GroupHeader`, `SettingsGroup`, `SettingsRow`, `IOSSwitch`, `LabeledSlider`, `RangeSlider`, `IntervalDisplay`, `EmptyState`, `ZoneThumbnail`, `QuietAccentButton`, `BorderlessButton`, `SegmentedControl`. Cross-couples the dwell range to the Realism preset via a small adapter (`_DwellRegistryAdapter`) — intentional and well-scoped.

**Stays form-row.** No reason to migrate.

---

## Tab: Behavior

**Current state.** Realism dial + seven sub-groups (Idle wander / Fatigue / Breaks / Overshoot / Anti-cluster / Stop after / Pre-start). Custom hero panel for the dial atop a flat stack of `SettingsGroup`s, each with a master `IOSSwitch` row gating dependent slider rows.

**Compliance.** ✅ Spacing, hairline-rules, three-tier typography, mono numerics, unit formatting, action-button-chevron rule. ⚠️ `GroupHeader` text renders grey (`#6b7280`) per `qss.py:224` — the spec says section labels should be teal. ⚠️ No active-state indicator on a master-on group — would mirror the Record tab's left stripe.

**Complexity.** SMALL.

**Specific changes.**

- `ui/qss.py:224-227` — change `QLabel[role="group-header"]` color from `t.TEXT_TERTIARY` (or whatever it resolves to) to `t.ACCENT`. **One line. Fixes Behavior, Hotkeys, Timers, Stats, Settings simultaneously.** `[safe]`
- Add a 3 px teal left stripe to active (master-enabled) groups, mirroring the Record tab's expanded-step pattern. Add a `[active="true"]` attribute on `SettingsGroup` and a QSS rule. `[safe]`
- Optionally dim the GroupHeader text when its master switch is off, so the master/detail relationship is more discoverable. `[safe]`

**Dependencies.** `SettingsGroup`, `SettingsRow`, `GroupHeader`, `IOSSwitch`, `LabeledSlider`. `RealismStub` is exported and used on Click + Record pages (cross-page sync via `app._adv_vars` / `app._adv_sliders`). **Stays form-row** — migration to Card/Field would force a rebuild of the master/detail logic for no visual win.

---

## Tab: Hotkeys

**Current state.** Three groups: Global hotkeys (Start / Stop rebindable + Esc locked), Alerts (Sound on stop), In-app shortcuts (read-only command list). Form-row layout.

**Compliance.** ✅ Almost everything. ⚠️ Same grey-not-teal `GroupHeader` issue (fixed by the qss.py change above).

**Complexity.** SMALL.

**Specific changes.**

- The qss.py group-header color fix above. `[safe]`
- Verify `KeyChip` widget at `ui/widgets/key_chip.py` uses mono font + 14 px body size (should already). `[safe]`
- Consider a 🔒 prefix or `role="locked"` on the Emergency-stop row to emphasize non-rebindability. `[safe]`

**Dependencies.** Same form-row toolkit. Polls `app.commands` for the in-app shortcuts list. **Stays form-row.**

---

## Tab: Timers

**Current state.** Two groups: Settings (jitter toggle), Timers (list of `TimerRow`s or empty state). `TimerRow` is a **custom widget**, not a `SettingsRow` — two-line layout, top has key+enable+remove, bottom has interval+unit+badge. Bypasses the `SettingsGroup` hairline logic.

**Compliance.** ⚠️ 8 px grid: top row compliant, bottom row uses a hardcoded 36 px left indent for badge alignment (non-standard). ⚠️ Mono numerics: interval value sits in a default `QDoubleSpinBox` font, not mono. ⚠️ Unit formatting: interval values render as raw float (`1.5`, `15`) without `fmt_delay`'s 3-decimal rule — and units come from a separate `QComboBox` rather than baked into the displayed value. ⚠️ Same grey-`GroupHeader` issue.

**Complexity.** MEDIUM (structural — `TimerRow` should either inherit from `SettingsRow` with a custom layout override, or be refactored into two stacked SettingsRows with shared `last` state management).

**Specific changes.**

- qss.py group-header color fix. `[safe]`
- Apply mono font to `QDoubleSpinBox` on form pages via a QSS rule keyed on a role attribute. `[safe]`
- Reformat interval display to use a single label like `"Every 15.000 s"` instead of a spinbox + combo side-by-side. `[risky — interaction redesign]`
- Refactor `TimerRow` to inherit from `SettingsRow` so it picks up the canonical hairline + spacing logic. `[risky — refactor]`
- Replace the hardcoded 36 px bottom-row indent with `t.ROW_PAD_X + badge_width + spacing` math, or remove the indent entirely. `[safe]`

**Dependencies.** Form-row primitives + custom `TimerRow`. Persists to `cfg["key_timers"]` via `serialize_timers()`. **Recommend staying form-row** but with the `TimerRow` standardization above.

---

## Tab: Stats

**Current state.** Five live counters (Total clicks, CPM, Elapsed, Avg interval, Last position) in a single `SettingsGroup`. Right-aligned mono values updated via `tick()` each frame.

**Compliance.** ✅ Spacing, hairlines, teal restraint. ❌ **Mono for numerics**: `role="stat-value"` is set but the QSS rule may not be wired (`SIZE_STAT_VALUE = 28` exists in theme but the actual styling appears to rely on inheritance — needs verification). ⚠️ Unit formatting inconsistency: Elapsed uses `format_elapsed()` (HH:MM:SS), CPM uses `.1f`, avg interval uses `.2f`, last position uses `(X, Y)`. No single rule.

**Complexity.** SMALL (cosmetic only).

**Specific changes.**

- `ui/cards/stats.py:55` — make the `stat-value` role's mono styling explicit, either by adding mono font to the role's QSS rule or by setting the font directly on the QLabel. `[safe]`
- `ui/cards/stats.py:76-81` — normalize CPM and avg-interval precision (both `.1f` or both `.2f`, not mixed). `[safe]`
- Either replace `GroupHeader("Session")` with `SectionLabel("Session")` (if the latter is the canonical in-card eyebrow) or document the choice. `[safe]`

**Dependencies.** Form-row primitives. Stat values are bare mono labels — **not unified** with AI tab's `_StatChip` pillboxes. Agents recommend keeping the split (different contexts).

---

## Tab: Monitor

**Current state.** `MonitorCard` — single `Card` with handcrafted `QHBoxLayout` rows (URL display, Server config, Phone controls), state pill in header, two opt-in toggles. Mixes the Card pattern with raw layout boilerplate.

**Compliance.** ⚠️ 8 px grid: spacing values are correct but applied via raw layouts instead of `SettingsGroup` automation. ⚠️ Section eyebrow: uses `SectionLabel` which renders grey, not teal (qss.py:116-120). ⚠️ Has an explicit `QFrame` divider rule (lines 212-216) — should be replaced by whitespace. ⚠️ Active-state indicator: state pill works but no card-level active stripe when listening. ⚠️ "Regenerate token" button is destructive in semantic (old phone URLs die) but rendered neutral.

**Complexity.** MEDIUM (structural — most of the work is migrating handcrafted rows to `SettingsRow` for consistency).

**Specific changes.**

- `ui/cards/monitor.py:45-79` — refactor URL display into a `SettingsRow` with the URL label as the title and Copy/Regenerate buttons in the control area. `[risky — visible layout change]`
- Update `SectionLabel`'s QSS rule (`qss.py:116-120`) to use `t.ACCENT` if teal eyebrows are the spec. `[safe]`
- `ui/cards/monitor.py:212-216` — remove the explicit divider QFrame; use `body.addSpacing(t.SP_XL)` instead. `[safe]`
- `ui/cards/monitor.py:86-208` — migrate enable / port / monitor / FPS / resolution / quality rows to `SettingsRow` instances. `[risky — touches every config row]`
- Add a warning tone to "Regenerate token" (amber border or text) since it invalidates existing phone URLs. `[safe]`
- Add a 3 px teal left stripe to the card while the server is listening. `[safe]`

**Dependencies.** `Card`, `IOSSwitch`, `SectionLabel`, `StatePill`. **Does not use** `SettingsGroup` / `SettingsRow` (this is the gap). Shares monitor enumeration logic (`_screen_label()` etc.) with Settings tab — **duplicate code**, extract.

---

## Tab: Settings

**Current state.** Three groups: Display (target monitor), Input (keyboard backend + Serial HID port), Diagnostics (mouse trace recorder). Pure form-row layout.

**Compliance.** ✅ Mostly compliant — spacing, hairlines absent, three-tier typography, action-button chevrons absent, destructive vs safe (no destructive actions). ⚠️ Same grey-`GroupHeader` issue. ⚠️ Event count display uses `f"{n:,} events"` (locale comma-separated); Stats uses `.1f` / `.2f`; no canonical numeric formatter.

**Complexity.** SMALL.

**Specific changes.**

- qss.py group-header color fix. `[safe]`
- `ui/cards/settings.py:165-202` — `_screen_label()` is duplicated with `monitor.py:377-401`. Extract to `ui/format.py` or a new `ui/screen_utils.py`. `[safe — refactor]`
- Optionally introduce `fmt_count(n)` in `ui/format.py` so the event count formatter is shared. `[safe]`

**Dependencies.** Form-row primitives. Code-shares monitor enumeration with Monitor tab.

---

## Tab: Help

**Current state.** Read-only documentation. Centered max-width column (820 px) with semantic helpers (`_title`, `_lead`, `_h2`, `_p`, `_ul`, `_ol`, `_kv`, `_faq`). Pure typography, no widgets, no interactivity.

**Compliance.** ✅ Almost all N/A or compliant — typography hierarchy is good, hotkey values render mono, no chevrons / no destructive actions / no empty states (correctly N/A). ⚠️ The `_kv()` helper renders **key labels in teal** (`help_page.py:252`) — this technically violates the "teal for primary CTAs / section labels only" rule. Agent recommends either documenting the exception or switching to `ACCENT_TEXT` (lighter cyan).

**Complexity.** SMALL.

**Specific changes.**

- `ui/pages/help_page.py:252` — change `_kv()` key label color from `t.ACCENT` to `t.ACCENT_TEXT` (still teal-family, but lighter and signals "label" not "primary action"). `[safe]`
- Inline title styling at lines 185-192 could be extracted to a theme constant. Low priority. `[safe]`

**Dependencies.** None — pure QLabel stacks. If Help grows substantially, externalize to Markdown + WebView.

---

## Cross-cutting findings (priority order)

| # | Finding | Tabs affected | Effort | Risk |
|---|---|---|---|---|
| 1 | `GroupHeader` text renders grey, spec says teal. Single QSS rule swap in `qss.py:224-227`: `color: {t.TEXT_TERTIARY}` → `color: {t.ACCENT}` | Behavior, Hotkeys, Timers, Stats, Settings | 1 line | Safe |
| 2 | `SectionLabel` renders grey at 10 px in `qss.py:116-120`. Same fix in spirit — bump color to teal, possibly bump size to 11 px to match `SIZE_SECTION_LABEL` token | Monitor (only place SectionLabel is used outside cards that wrap it) | 1 line | Safe |
| 3 | `_screen_label()` duplicated between `monitor.py` and `settings.py`. Extract | Monitor, Settings | ~30 min | Safe |
| 4 | Monitor card uses handcrafted `QHBoxLayout` rows instead of `SettingsRow`. Migrate | Monitor | ~2 h | Visible layout shift |
| 5 | AI hero "setup notes" toggle should use the `Expander` widget for consistency | AI | ~30 min | Visible behavior change |
| 6 | Timers `TimerRow` is custom and bypasses the `SettingsRow` contract. Either refactor `TimerRow` to inherit, or split into two stacked `SettingsRow`s | Timers | ~2 h | Visible behavior change |
| 7 | Unit-formatting inconsistency: `fmt_delay` is canonical for time but Stats / Settings / Timers use ad-hoc `.1f` / `.2f` / `f"{n:,}"`. Add `fmt_count`, `fmt_percent`, etc. and apply | Stats, Settings, Timers | ~1 h | Safe |
| 8 | Stats `stat-value` role mono styling needs verification | Stats | ~10 min | Safe |
| 9 | Help `_kv()` key labels are teal — slight teal-discipline violation | Help | 1 line | Safe |
| 10 | Active-state left stripe could extend from step cards (Record) to active master groups (Behavior) and to listening Monitor cards | Behavior, Monitor | ~1 h | Safe |

**Recommended sequencing:**

1. Bundle items 1, 2, 8, 9 into a single "global teal token + mono polish" PR — touches `qss.py`, `theme.py`, `stats.py:55`, `help_page.py:252`. ~30 minutes total. Fixes 6 tabs in one shot.
2. Item 3 (extract `_screen_label`) + item 7 (canonical `fmt_*` helpers) into a "format utilities" PR. ~1 hour.
3. Items 4, 5, 6 (Monitor refactor, AI Expander swap, Timers row standardization) each as their own PRs since they're visible interaction changes that warrant individual review.
4. Item 10 (extending the left-stripe pattern) as a final consistency pass.

**Document the form-row vs card-based split.** Add a short paragraph to whatever design-system doc lives in the repo (or `CLAUDE.md`) noting that mode pages (Click, Record, AI) use Card→Section→Field while config pages (Behavior, Hotkeys, Timers, Stats, Monitor, Settings, Help) use GroupHeader→SettingsGroup→SettingsRow. Prevents future drift.

No code modified in this session.
