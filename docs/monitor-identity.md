# Monitor identity and configuration preservation

Click/Record monitor selection uses Qt indices (zero-based); AI uses MSS indices
(one-based physical screens, with zero meaning the virtual desktop). They are
not interchangeable.

The config now stores `target_monitor_identity` and `ai_monitor_identity` next
to the legacy index settings. Identities contain the Qt screen name, geometry,
model and serial number when available. Matching prefers a unique serial/model,
then name/geometry, model/geometry, unique model, name and geometry, in that order.
The saved index is used only when identity matching fails. If that index is also
unavailable, the first attached physical screen is used. Auto and virtual desktop
remain special choices and clear the corresponding identity.

AI maps physical MSS rectangles to Qt screen identities using the application's
DIP-to-physical conversion. Its independent index is resolved at bot startup and
when calibration or capture tools need a monitor. Unmatched MSS screens retain
geometry-only identity. Existing identity is preserved when a display is absent,
so reconnecting it can restore selection instead of saving the fallback screen.
Settings, zone-map menus and viewport menus show the resolved selection.

For old index-only configs, the first launch associates the current selection
with the currently enumerated screen in memory; the normal save persists it.
There is no way to reconstruct which monitor an old index referred to before
reordering. Reselect the intended Click and AI screens once after this upgrade.
Identical monitors without unique hardware metadata can still be ambiguous;
geometry and the old index provide best-effort fallback, not a hardware guarantee.

The timing details expander now starts closed; selecting the interval row opens
it explicitly. While idle, Current Run becomes Run Readiness and shows the next
setup action (or Ready), plus enabled Record steps when applicable.

Validation covers string-index round trips, independent Qt/MSS reordering,
geometry/name changes, missing-screen fallback without overwriting identity,
and persistence of unrelated settings. Full GUI checks use temporary config
paths. Packaged startup tests use an executable copy in a fresh scratch directory.
The restored production config must have the same SHA-256 before and after work.
