"""Batch-shrink research videos before analyzing them.

Focus-group footage is mostly talking heads, so a 720p H.264 proxy at a modest
quality looks fine in the highlight reel while being far smaller than the
original (often 5-10x). Run this once over a folder of big session files, then
point GroupThink at the smaller copies.

    python -m groupthink.compress --in ~/sessions --out ~/sessions_small

The proxies are normal .mp4 files — use them for upload, the local-folder mode,
or the CLI just like the originals.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from .config import load_settings

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpg", ".mpeg"}


def list_videos(folder: str) -> list[str]:
    """Video files directly inside `folder`, sorted by name."""
    p = Path(folder).expanduser()
    if not p.is_dir():
        return []
    return sorted(
        str(f) for f in p.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS
    )


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


def compress_video(
    src: str,
    dst: str,
    height: int = 720,
    crf: int = 28,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Transcode `src` to a smaller H.264 proxy at `dst`.

    Scales down to at most `height` pixels tall (never upscales), keeping aspect
    ratio with even dimensions. `crf` controls quality/size (lower = better/
    bigger; 23 is visually transparent, 28 is a good small-file default).
    """
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale=-2:'min(ih,{height})'"
    subprocess.run(
        [
            ffmpeg_bin, "-y", "-i", src,
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            dst,
        ],
        capture_output=True,
        check=True,
    )
    return dst


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="groupthink.compress",
        description="Batch-shrink videos before analyzing them with GroupThink.",
    )
    parser.add_argument("--in", dest="in_dir", required=True, help="Folder of source videos.")
    parser.add_argument("--out", dest="out_dir", required=True, help="Where to write the smaller copies.")
    parser.add_argument("--height", type=int, default=720, help="Max output height in pixels (default 720).")
    parser.add_argument("--crf", type=int, default=28, help="Quality 18-32; lower = better/bigger (default 28).")
    args = parser.parse_args(argv)

    settings = load_settings()
    videos = list_videos(args.in_dir)
    if not videos:
        parser.error(f"No videos found in {args.in_dir}")

    print(f"Compressing {len(videos)} video(s) → {args.out_dir}  (≤{args.height}px tall, crf {args.crf})\n")
    total_in = total_out = 0
    for i, src in enumerate(videos, start=1):
        name = Path(src).name
        print(f"  [{i}/{len(videos)}] {name} …", end=" ", flush=True)
        dst = str(Path(args.out_dir).expanduser() / (Path(src).stem + ".mp4"))
        try:
            compress_video(src, dst, args.height, args.crf, settings.ffmpeg_bin)
        except subprocess.CalledProcessError as exc:
            print(f"FAILED ({exc})")
            continue
        si = Path(src).stat().st_size
        so = Path(dst).stat().st_size
        total_in += si
        total_out += so
        print(f"{human_size(si)} → {human_size(so)}  ({so / si * 100:.0f}%)")

    if total_in:
        print(
            f"\nTotal: {human_size(total_in)} → {human_size(total_out)}  "
            f"({total_out / total_in * 100:.0f}% of original)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
