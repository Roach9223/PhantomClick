# rs3vision (bundled binary)

`rs3vision` is the vision core the AI tab uses for CTS color clustering,
point-array (TPA) math, frame diffing, and bitmap OCR. The Rust part ships
in this repo as a prebuilt extension module, `_rs3vision.pyd`. The Python
files next to it (`__init__.py`, `chat.py`, `chat_config.py`, `types.py`,
`uptext.py`, `xp_drops.py`) are thin wrappers and domain parsers on top of
that binary.

## Version

`rs3vision.__version__` reports `0.1.0`. The `.pyd` in this folder is
byte-identical (MD5 `b405a748586865063276e518f98bcad3`) to the one in the
source tree's `crates/rs3v-py/python/rs3vision/`, and the six Python files
match the source tree too, so what is committed here is exactly what the
last `maturin develop --release` produced on 2026-04-12.

## What the binary exports

From `python -c "import rs3vision._rs3vision as m; print(dir(m))"`:

| Submodule | Functions |
|---|---|
| `color` | `find(frame, target, cts=..., tol=..., roi=...)`, `count(...)` |
| `tpa` | `cluster`, `bounds`, `centroid`, `filter_size`, `dilate`, `erode` |
| `feature` | `diff`, `changed_in_roi` |
| `ocr` | `Font`, `load_font`, `read`, `read_rvf`, `write_rvf`, `extract_regions`, `phash_bitmap`, `hamming64` |
| `CTS` | `CTS1`, `CTS2`, `CTS3` (also exported at top level) |

Frames are numpy arrays of shape `(H, W, 3)`, dtype `uint8`, BGR channel
order (the layout mss and Win32 BitBlt produce). `rs3vision/__init__.py`
re-exports the submodules and adds `chatbox_events`, `read_uptext`,
`read_xp_drops`, and the `ChatConfig` loader that reads
`templates/chat_colors.toml`.

## ABI constraints

- **Python 3.11 only.** The crate is built with PyO3 `abi3-py311`, so the
  module loads on CPython 3.11 and newer in principle, but the project pins
  3.11 because that is the only interpreter it has been tested and shipped
  with. Under 3.10 or older the import fails with `DLL load failed`.
- **numpy 1.x.** The bindings use the `numpy` Rust crate 0.22 and were
  compiled with numpy 1.26 installed. `requirements.txt` pins `numpy<2`
  until someone rebuilds against numpy 2 and re-verifies `color.find()` on
  a live frame.
- **Windows x64 only.** No Linux or macOS build exists.

## Where the source lives

The Rust source lives outside this repo, on this machine at:

```
H:\02_PROGRAMMING\Game_Bots\RS3_AI\rs3vision-rs\
  Cargo.toml                 workspace (rs3v-core + rs3v-py), version 0.1.0
  crates\rs3v-core\src\      color.rs, tpa.rs, dtm.rs, feature.rs, minimap.rs, ocr\
  crates\rs3v-py\src\lib.rs  PyO3 bindings
  crates\rs3v-py\pyproject.toml   maturin config (module-name rs3vision._rs3vision)
  crates\rs3v-py\python\rs3vision\   the Python wrapper files mirrored here
  rust-toolchain.toml        stable channel
```

That folder is **not a git repository**. If it is lost, the `.pyd` here
cannot be rebuilt. Putting `rs3vision-rs` under version control (its own
repo, or a git submodule of this one) is the single most useful thing to
do for the long-term health of the AI tab.

Neighbouring folders `rs3vision-studio`, `rs3vision-tools`, and
`rs3vision-mcp` are the pre-merge Studio app and are not needed to build
the binary.

## How to rebuild

Prerequisites: Rust stable 1.78 or newer (`cargo 1.94` is installed under
`H:\00_TOOLCHAIN\.Rust`), MSVC Build Tools, Python 3.11, and `maturin`
(`py -3.11 -m pip install "maturin>=1.5,<2"`; it is not currently
installed).

```powershell
$env:CARGO_HOME  = 'H:\00_TOOLCHAIN\.Rust\cargo'
$env:RUSTUP_HOME = 'H:\00_TOOLCHAIN\.Rust\rustup'
cd H:\02_PROGRAMMING\Game_Bots\RS3_AI\rs3vision-rs\crates\rs3v-py

# Build the wheel (does not install anything)
py -3.11 -m maturin build --release

# The .pyd ends up inside the wheel under target\wheels\. Unzip it, or run
# `maturin develop --release` inside a 3.11 venv and copy the module from
# that venv's site-packages\rs3vision\ into this folder.
```

After copying the new `_rs3vision.pyd` (and `_rs3vision.pdb` if you want
symbols; it is gitignored) into `AutoClicker/rs3vision/`, confirm:

```powershell
py -3.11 -c "import rs3vision; print(rs3vision.__version__, rs3vision.color.find)"
```

If the Python wrapper files changed upstream, copy those too; they must
match the binary's exported names.

## Why it is vendored instead of pip-installed

PyInstaller needs the `.pyd` as an explicit binary (see `PhantomClick.spec`),
and the AI tab has to work from a clean `git clone` without a Rust
toolchain. Committing the built module is the trade-off that makes both
true. The cost is the rebuild story above.
