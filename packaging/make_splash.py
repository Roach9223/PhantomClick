"""Generate ``packaging/splash.png``, the PyInstaller onefile splash shown
while the single-file build unpacks on first launch (10 to 20 s).

Run once; the PNG is committed so the build stays reproducible without
re-running this (Pillow is already a project dependency)::

    python packaging/make_splash.py

Palette matches the command deck theme in ``ui/theme.py``: near-black
background, a bordered 8 px panel, Barlow Bold wordmark, JetBrains Mono
subtext, and a single 6 px lime square as the only accent.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 480, 240
BG = (0x0B, 0x0D, 0x0C)         # theme.BG
PANEL = (0x11, 0x14, 0x13)      # theme.SURFACE
PANEL_LINE = (0x1F, 0x24, 0x22) # theme.BORDER
LIME = (0x9B, 0xE1, 0x5D)       # theme.ACCENT
FG = (0xE6, 0xE4, 0xDF)         # theme.TEXT_PRIMARY
MUTED = (0x8A, 0x8D, 0x87)      # theme.TEXT_TERTIARY

FONTS = Path(__file__).resolve().parent.parent / "ui" / "fonts"


def _font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    """First font that loads, else Pillow's bundled default."""
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

    # Bordered panel, 8 px radius.
    d.rounded_rectangle([12, 12, W - 12, H - 12], radius=8,
                        fill=PANEL, outline=PANEL_LINE, width=1)

    wordmark = _font([str(FONTS / "Barlow-Bold.ttf"), "segoeuib.ttf", "arialbd.ttf"], 40)
    sub = _font([str(FONTS / "JetBrainsMono-Regular.ttf"), "CascadiaMono.ttf", "consola.ttf"], 12)

    title = "PhantomClick"
    tb = d.textbbox((0, 0), title, font=wordmark)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    ty = 78

    # Lime square + wordmark, centred as one group.
    sq = 6
    gap = 14
    group_w = sq + gap + tw
    gx = (W - group_w) // 2
    d.rectangle([gx, ty + th // 2 - sq // 2 + 4, gx + sq, ty + th // 2 + sq // 2 + 4], fill=LIME)
    d.text((gx + sq + gap - tb[0], ty), title, font=wordmark, fill=FG)

    msg = "STARTING UP. FIRST LAUNCH TAKES A FEW SECONDS."
    sb = d.textbbox((0, 0), msg, font=sub)
    sw = sb[2] - sb[0]
    d.text(((W - sw) // 2, ty + 74), msg, font=sub, fill=MUTED)

    img.save(out, "PNG")
    print(f"wrote {out} ({W}x{H})")


if __name__ == "__main__":
    main()
