"""Compose the splash and the boot-animation frames from the Blender renders.

Inputs (from ``blender_mark.py``): ``render/mark_1024.png`` and
``render/boot/frame_NNNN.png`` (48 transparent 640 x 320 frames).

Outputs, committed so the build never needs Blender:

    packaging/splash.png          480 x 240, the PyInstaller onefile splash
    packaging/boot/frame_NN.png   48 frames, 640 x 320, played by ui/boot_splash.py

Both are the mark on the left and the Barlow wordmark on the right, on the
slate palette from ``ui/theme.py``. The splash is the last frame scaled,
so what the user sees while the exe unpacks is the same picture the boot
animation lands on.

    python packaging/make_boot.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
RENDER = HERE / "render"
BOOT = HERE / "boot"
FONTS = HERE.parent / "ui" / "fonts"

BG = (0x0E, 0x11, 0x16)          # theme.BG
BORDER = (0x26, 0x30, 0x3B)      # theme.BORDER
FG = (0xDC, 0xE3, 0xEA)          # theme.TEXT_PRIMARY
MUTED = (0x7C, 0x88, 0x94)       # theme.TEXT_TERTIARY
ICE = (0x7C, 0xC4, 0xF2)         # theme.ACCENT

FRAME_W, FRAME_H = 640, 320
SPLASH_W, SPLASH_H = 480, 240


def _font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def compose(mark: Image.Image, w: int, h: int, *, progress: float = 1.0,
            sub: str = "") -> Image.Image:
    """One frame: slate ground, hairline frame, the mark on the left third,
    the wordmark on the right. ``progress`` fades the wordmark in over the
    first part of the boot so the eye lands on the mark first."""
    img = Image.new("RGBA", (w, h), BG + (255,))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, w - 2, h - 2], radius=8, outline=BORDER, width=1)
    # Corner marks on the frame itself, like the deck's viewport.
    arm = max(10, w // 40)
    for (x, y, dx, dy) in ((8, 8, 1, 1), (w - 9, 8, -1, 1), (8, h - 9, 1, -1), (w - 9, h - 9, -1, -1)):
        d.line([(x, y), (x + dx * arm, y)], fill=BORDER, width=1)
        d.line([(x, y), (x, y + dy * arm)], fill=BORDER, width=1)

    # Mark: square, height-fit to the frame with a margin.
    side = int(h * 0.86)
    m = mark.resize((side, side), Image.LANCZOS)
    mx = int(w * 0.06)
    my = (h - side) // 2
    img.alpha_composite(m, (mx, my))

    # Wordmark and subtext to the right of the mark.
    scale = w / FRAME_W
    word = _font([str(FONTS / "Barlow-Bold.ttf"), "segoeuib.ttf", "arialbd.ttf"], int(52 * scale))
    small = _font([str(FONTS / "Barlow-SemiBold.ttf"), "segoeuib.ttf"], int(14 * scale))
    mono = _font([str(FONTS / "JetBrainsMono-Medium.ttf"), "consola.ttf"], int(13 * scale))
    tx = mx + side + int(w * 0.05)
    title = "PhantomClick"
    # Fit the wordmark to the space left of the frame's right margin.
    room = w - tx - int(w * 0.05)
    size = int(52 * scale)
    while size > 16:
        word = _font([str(FONTS / "Barlow-Bold.ttf"), "segoeuib.ttf", "arialbd.ttf"], size)
        tb = d.textbbox((0, 0), title, font=word)
        if tb[2] - tb[0] <= room:
            break
        size -= 2
    tb = d.textbbox((0, 0), title, font=word)
    th = tb[3] - tb[1]
    ty = h // 2 - th // 2 - int(18 * scale)
    alpha = int(255 * max(0.0, min(1.0, progress)))
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((tx - tb[0], ty - tb[1]), title, font=word, fill=FG + (alpha,))
    tag = "HUMAN-LIKE CLICK ENGINE"
    ld.text((tx, ty + th + int(12 * scale)), tag, font=small, fill=MUTED + (alpha,))
    if sub:
        msize = int(13 * scale)
        while msize > 8:
            mono = _font([str(FONTS / "JetBrainsMono-Medium.ttf"), "consola.ttf"], msize)
            sb = ld.textbbox((0, 0), sub, font=mono)
            if sb[2] - sb[0] <= room:
                break
            msize -= 1
        ld.text((tx, ty + th + int(34 * scale)), sub, font=mono, fill=ICE + (alpha,))
    img.alpha_composite(layer)
    return img


def main() -> None:
    frames = sorted((RENDER / "boot").glob("frame_*.png"))
    still = RENDER / "mark_1024.png"
    if not frames or not still.exists():
        raise SystemExit("render first: blender -b -P packaging/blender_mark.py")

    if BOOT.exists():
        shutil.rmtree(BOOT)
    BOOT.mkdir()
    n = len(frames)
    for i, path in enumerate(frames):
        mark = Image.open(path).convert("RGBA")   # square render
        progress = (i - 14) / 16.0
        img = compose(mark, FRAME_W, FRAME_H, progress=progress,
                      sub="LOCAL · OFFLINE · NO TELEMETRY" if i >= n - 12 else "")
        img.convert("RGB").save(BOOT / f"frame_{i:02d}.png", optimize=True)
    print(f"wrote {n} frames to {BOOT}")

    mark = Image.open(still).convert("RGBA")
    splash = compose(mark, SPLASH_W, SPLASH_H, sub="FIRST LAUNCH TAKES A FEW SECONDS")
    splash.convert("RGB").save(HERE / "splash.png", "PNG")
    print(f"wrote {HERE / 'splash.png'} ({SPLASH_W}x{SPLASH_H})")


if __name__ == "__main__":
    main()
