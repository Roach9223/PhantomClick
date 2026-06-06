# PostMessage (background-play) backend — status & roadmap

## TL;DR

`input_mode: post_message` is **not implemented yet**. Using it
raises `NotImplementedError` at the first click/move. Until it lands,
set `input_mode: real` in your task or script — that routes through
the humanized visible-cursor backend which ships in every build.

## Why PostMessage?

- **No visible cursor hijack.** The Studio can click inside the RS3
  client while you use other windows / other monitors normally.
- **No anti-cheat friction from foreground-focus checks** — the client
  processes the synthesised `WM_LBUTTONDOWN` / `WM_LBUTTONUP` messages
  even when it isn't the active window.
- **Safer failsafes** — corner-failsafe and foreground-window guards
  aren't needed because there's no physical cursor to worry about.

## What's needed to implement it

1. **Client window discovery** — locate `rs2client.exe`'s HWND.
   `FindWindowW(lpClassName=NULL, lpWindowName="RuneScape")` is the
   obvious first try, but the NXT client's title varies; may need a
   `EnumWindows` sweep filtering by PID + class name.
2. **Coordinate translation** — block outputs are monitor-space
   pixels. The client expects client-relative coordinates. Use
   `ScreenToClient(hwnd, pt)` and pack into `LPARAM = MAKELPARAM(x, y)`.
3. **Mouse-event sequencing** — send the triplet
   `WM_MOUSEMOVE` → `WM_LBUTTONDOWN` → (hold) → `WM_LBUTTONUP`.
   Include the correct `wParam` flags (`MK_LBUTTON` while held).
4. **Keyboard events** — `WM_KEYDOWN` / `WM_KEYUP` with `lParam` carrying
   the scan code, repeat count, and transition-state bits. RS3 ignores
   WM_CHAR for some inputs; prefer WM_KEYDOWN + VK_* codes.
5. **MouseAPI adapter** — implement `rs3vision_studio.humanize.mouse_api.MouseAPI`
   over `PostMessage` so the existing humanizer path generator / fatigue /
   anti-cluster layers work without changes.

## What we already have that helps

- `rs3vision_studio/humanize/paths.py` is backend-agnostic; it accepts
  any `MouseAPI` and produces paths via `set_position` + press/release.
- `rs3vision_studio/humanize/fatigue.py` is pure math — reuses as-is.
- `rs3vision_studio/humanize/anti_cluster.py` operates on
  screen-space points; works the same for both backends.

## Why we paused here

PostMessage + NXT is nontrivial DLL-injection territory. Getting it
right without breaking on client updates needs real NXT research that
wasn't in scope for the humanization sprint. The stub now prints a
clear error pointing users at `input_mode: real`.

## Reopening the work

When you're ready to attack this again, the starting point is:

- Read `rs3vision_studio/input/__init__.py` — the protocol hasn't
  changed.
- Implement `PostMessageMouseAPI` in `humanize/mouse_api.py`.
- Wire `PostMessageBackend` to use it with the same `HumanizerConfig`
  flow the real backend uses.
- Add a launch-time check that warns if the target client window
  isn't found, so users don't get confused NotFoundError-style.
