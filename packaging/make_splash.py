"""Generate ``packaging/splash.png`` — the PyInstaller onefile splash shown
while the single-file build unpacks on first launch (~10-20 s).

Run once; the PNG is committed so the build stays reproducible without
re-running this (Pillow is already a project dependency)::

    python packaging/make_splash.py

Palette matches the app theme: near-black slate surfaces, teal #22d3ee accent.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 480, 240
BG = (15, 17, 22)        # near-black slate (page background)
CARD = (22, 25, 32)      # slightly lighter inset panel
PANEL_LINE = (40, 44, 54)
TEAL = (34, 211, 238)    # #22d3ee accent
FG = (236, 239, 244)     # near-white wordmark
MUTED = (148, 158, 170)  # subtext


def _font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    """First system font that loads, else Pillow's bundled default."""
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    out = Path(__file__).resolve().parent / "splash.png"
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Inset rounded panel.
    d.rounded_rectangle([12, 12, W - 12, H - 12], radius=16,
                        fill=CARD, outline=PANEL_LINE, width=1)

    wordmark = _font(["segoeuib.ttf", "arialbd.ttf"], 40)
    sub = _font(["segoeui.ttf", "arial.ttf"], 15)

    # Centered wordmark.
    title = "PhantomClick"
    tb = d.textbbox((0, 0), title, font=wordmark)
    tw = tb[2] - tb[0]
    tx = (W - tw) // 2
    ty = 76
    d.text((tx, ty), title, font=wordmark, fill=FG)

    # Teal accent underline.
    d.rounded_rectangle([tx, ty + 56, tx + tw, ty + 60], radius=2, fill=TEAL)

    # Centered subtext.
    msg = "Starting up — first launch takes a few seconds…"
    sb = d.textbbox((0, 0), msg, font=sub)
    sw = sb[2] - sb[0]
    d.text(((W - sw) // 2, ty + 80), msg, font=sub, fill=MUTED)

    img.save(out, "PNG")
    print(f"wrote {out} ({W}x{H})")


if __name__ == "__main__":
    main()
