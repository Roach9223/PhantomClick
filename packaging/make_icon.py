"""Generate ``packaging/phantomclick.ico`` from ``packaging/icon_source.png``.

Run once; the .ico is committed and used by ``PhantomClick.spec`` for the
exe's file icon and as the app's window/taskbar icon (set in
``ui/app.py`` run()). Source is the 1024x1024 RGBA app icon.

    python packaging/make_icon.py

Windows .ico images max out at 256x256; we emit the standard size ladder
so Explorer, the taskbar, and alt-tab each pick a crisp variant.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    here = Path(__file__).resolve().parent
    src = here / "icon_source.png"
    out = here / "phantomclick.ico"

    img = Image.open(src).convert("RGBA")

    # ICO must be square; center-crop if the source ever isn't.
    if img.width != img.height:
        side = min(img.width, img.height)
        left = (img.width - side) // 2
        top = (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side))

    img.save(out, format="ICO", sizes=SIZES)
    print(f"wrote {out} with sizes {[s[0] for s in SIZES]}")


if __name__ == "__main__":
    main()
