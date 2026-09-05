"""Compose the README hero and the release video from the Blender renders.

Inputs (from ``blender_mark.py --hero --video``): ``render/hero_2160.png``
and ``render/video/frame_NNNN.png`` (96 square 1080 px frames).

Outputs, committed under ``docs/media``:

    docs/media/hero.png        3840 x 2160, the mark and wordmark
    docs/media/hero.webp       1920 x 1080, what the README embeds
    docs/media/boot.mp4        1920 x 1080 at 30 fps, for the release page
    docs/media/boot.gif        960 x 540, for the README (GitHub plays GIFs inline)

Same composition as the splash and boot frames (``make_boot.compose``),
so every surface the mark appears on is one picture. Needs ffmpeg on
PATH for the video and the GIF.

    python packaging/make_media.py
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from make_boot import compose

HERE = Path(__file__).resolve().parent
RENDER = HERE / "render"
MEDIA = HERE.parent / "docs" / "media"

TAGLINE = "LOCAL · OFFLINE · NO TELEMETRY"


def hero() -> None:
    still = RENDER / "hero_2160.png"
    if not still.exists():
        raise SystemExit("render first: blender -b -P packaging/blender_mark.py -- --hero")
    mark = Image.open(still).convert("RGBA")
    img = compose(mark, 3840, 2160, sub=TAGLINE)
    MEDIA.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(MEDIA / "hero.png", "PNG", optimize=True)
    img.convert("RGB").resize((1920, 1080), Image.LANCZOS).save(
        MEDIA / "hero.webp", "WEBP", quality=88, method=6)
    print("wrote", MEDIA / "hero.png", "and hero.webp")


def video() -> None:
    frames = sorted((RENDER / "video").glob("frame_*.png"))
    if not frames:
        raise SystemExit("render first: blender -b -P packaging/blender_mark.py -- --video")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not on PATH")
    n = len(frames)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for i, path in enumerate(frames):
            mark = Image.open(path).convert("RGBA")
            progress = (i - 14) / 16.0
            img = compose(mark, 1920, 1080, progress=progress,
                          sub=TAGLINE if i >= 62 else "")
            img.convert("RGB").save(tmpdir / f"f_{i:04d}.png")
        MEDIA.mkdir(parents=True, exist_ok=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "30",
                        "-i", str(tmpdir / "f_%04d.png"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                        "-movflags", "+faststart", str(MEDIA / "boot.mp4")], check=True)
        # GIF: palette pass for clean slate gradients, 960 wide, 24 fps.
        palette = tmpdir / "palette.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "30",
                        "-i", str(tmpdir / "f_%04d.png"),
                        "-vf", "fps=24,scale=960:-1:flags=lanczos,palettegen=max_colors=128",
                        str(palette)], check=True)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-framerate", "30",
                        "-i", str(tmpdir / "f_%04d.png"), "-i", str(palette),
                        "-lavfi", "fps=24,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5",
                        "-loop", "0", str(MEDIA / "boot.gif")], check=True)
    print(f"wrote {MEDIA / 'boot.mp4'} and boot.gif from {n} frames")


if __name__ == "__main__":
    hero()
    video()
