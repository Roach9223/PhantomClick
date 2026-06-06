# PhantomClick

A Windows auto-clicker built around one idea: *what looks human is human enough.*
The cursor physically travels along curved paths, dwells, jitters, fatigues, and
occasionally takes breaks; clicks land at randomized points inside a user-drawn
area; timings are sampled from log-normal distributions instead of uniform ones.

Three modes, one dark landscape window:

- **Click** — pick one area on screen; the engine clicks inside it forever.
- **Record** — build an ordered sequence of steps (click / track / color / key / pause / loop) that runs top-to-bottom and loops.
- **AI** — run a rule-based bot from the bundled library, dispatched through the same humanizer.

Everything runs locally — **no network, no telemetry, no auto-update.**

---

## Download & run

> **[⬇ Download the latest PhantomClick.exe](https://github.com/Roach9223/PhantomClick/releases/latest/download/PhantomClick.exe)**

No Python install required — download, double-click, go. **Windows 10/11 only.**

On first launch the app creates `config.json` and `phantomclick.log` next to the
`.exe`. The first start of a single-file build is a little slow while it unpacks;
subsequent runs are quicker. If Windows SmartScreen prompts, choose *More info →
Run anyway* (the build is unsigned).

---

## Features

| Area | What it does |
|---|---|
| **Humanization** | Bézier movement with overshoot/jitter, log-normal click delays, fatigue + scheduled breaks, idle wander, anti-cluster targeting, micro-jitter. One `realism` dial (0–1) drives all of it. |
| **Zones** | Rectangle / circle / polygon click areas with Gaussian center-bias. |
| **Tracking** | Multi-scale template matching follows a moving target; alternate views handle rotation / camera angle. |
| **Color steps** | Eyedropper a target color; click any matching pixel within tolerance, optionally scoped to a zone. |
| **Hotkeys** | Global Start / Stop (default **F6** / **F7**), corner emergency-stop. |
| **Key timers** | Passive concurrent keypresses (e.g. a potion macro every N minutes). |
| **Monitor** | Opt-in LAN screen stream + remote Start/Stop from your phone, token-protected. |
| **Input backends** | `pynput` (default), Interception driver, or Serial HID (Arduino Leonardo) — selectable. |

---

## Run from source

**Python 3.11 is required** — the bundled `rs3vision/_rs3vision.pyd` Rust vision
core is ABI-bound to 3.11.

```powershell
git clone https://github.com/Roach9223/PhantomClick.git
cd PhantomClick
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Optional input backends (only if you use them): `pip install interception-python`
(needs the Interception driver + reboot) and `pip install pyserial` (Arduino HID).

---

## Build the .exe yourself

```powershell
pwsh -File build.ps1          # or: pyinstaller PhantomClick.spec --noconfirm --clean
```

Output lands in `dist\PhantomClick.exe`. The build must run under Python 3.11
(see above). The PyInstaller config lives in `PhantomClick.spec`.

---

## Configuration

`config.json` is created next to the running app on first launch and is **not**
committed (it holds your screen calibration, Monitor token, and serial port).
Settings persist automatically on every meaningful change — there is no Save button.

---

## Project layout

```
main.py            entry point
ui/                PySide6 GUI (pages, cards, widgets, theme)
modules/           click engine, recorder, tracker, hotkeys, key input
utils/             humanizer, fatigue, idle wander, paths, logger
ai/                rule-based bot framework + bundled task library
rs3vision/         prebuilt Rust vision core (_rs3vision.pyd, Python 3.11)
firmware/          PhantomHID Arduino sketch (NXT-resistant keystrokes)
```

---

## License

[MIT](LICENSE).

*Disclaimer: PhantomClick is an independent, third-party input-automation tool.
It is not affiliated with or endorsed by any game publisher. Automating a game
may violate its terms of service — use at your own risk.*
