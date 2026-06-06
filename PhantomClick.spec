# PyInstaller build spec for PhantomClick (single-file Windows .exe).
#
#   Build:  pyinstaller PhantomClick.spec --noconfirm --clean
#   (or just run build.ps1, which pins the Python 3.11 interpreter.)
#
# MUST be built with Python 3.11 — rs3vision/_rs3vision.pyd is ABI-bound
# to 3.11; any other interpreter yields "ImportError: DLL load failed"
# at runtime on the first vision call.
#
# Why each piece is here:
#   - ai/tasks/library  : the *.task.yaml manifests + companion *.py bot
#       scripts. The AI tab enumerates the yaml and loads the .py BY FILE
#       PATH (importlib in ui/cards/ai.py), so PyInstaller never sees them
#       via static analysis — they must ship as data.
#   - rs3vision         : package source + templates/*.toml (read at import
#       by rs3vision/chat_config.py).
#   - _rs3vision.pyd    : the Rust vision core, shipped as an explicit
#       binary (mirrors the documented --collect-binaries rs3vision).
#   - collect_submodules("ai") : the dynamically-loaded bot scripts do
#       `from ai.bot import ...` / `from ai.captures import ...`; pulling
#       the whole ai tree in is what stops a Start-time ModuleNotFoundError.
#   - collect_submodules("pynput") : pynput resolves its win32 backend
#       dynamically.
#   - excludes tkinter/customtkinter : a legacy requirement; the runtime
#       UI is 100% PySide6, so Tk is dead weight.

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("ai/tasks/library", "ai/tasks/library"),
    ("rs3vision", "rs3vision"),
    ("packaging/phantomclick.ico", "packaging"),
]

binaries = [
    ("rs3vision/_rs3vision.pyd", "rs3vision"),
]

hiddenimports = collect_submodules("ai") + collect_submodules("pynput")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["customtkinter"],   # keep tkinter: the splash renderer uses Tcl/Tk
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

# Splash shown the instant the onefile starts unpacking (~10-20s on first
# launch) so a non-technical user gets immediate "it's loading" feedback.
# Dismissed from ui/app.py run() via pyi_splash once the main window appears.
splash = Splash(
    "packaging/splash.png",
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PhantomClick",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed GUI app, no console
    icon="packaging/phantomclick.ico",
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
