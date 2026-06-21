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
import functools
import platform
import sys
from pathlib import Path

from .config import load_settings

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpg", ".mpeg"}


@functools.lru_cache(maxsize=8)
def _encoder_works(ffmpeg_bin: str, encoder: str) -> bool:
    """Confirm an encoder actually runs (being *listed* doesn't mean it works —
    e.g. NVENC is listed even on machines with no NVIDIA GPU)."""
    try:
        subprocess.run(
            [ffmpeg_bin, "-y", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.1:r=5",
             "-c:v", encoder, "-f", "null", "-"],
            capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError):
        return False


@functools.lru_cache(maxsize=4)
def hardware_encoder(ffmpeg_bin: str = "ffmpeg") -> str | None:
    """Return a fast, *working* hardware H.264 encoder, or None.

    On macOS that's Apple's VideoToolbox (the media engine) — typically several
    times faster than software x264. Each candidate is verified with a tiny test
    encode before being trusted.
    """
    try:
        out = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    candidates = []
    if platform.system() == "Darwin" and "h264_videotoolbox" in out:
        candidates.append("h264_videotoolbox")
    if "h264_nvenc" in out:
        candidates.append("h264_nvenc")
    for encoder in candidates:
        if _encoder_works(ffmpeg_bin, encoder):
            return encoder
    return None


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
    skip_existing: bool = False,
    bitrate: str | None = None,
) -> str:
    """Transcode `src` to a smaller H.264 proxy at `dst`.

    Scales down to at most `height` pixels tall (never upscales), keeping aspect
    ratio with even dimensions. Uses a hardware encoder (Apple VideoToolbox /
    NVENC) when available for speed, falling back to software libx264 (`crf`
    controls quality/size there; lower = better/bigger).

    With `skip_existing`, a non-empty `dst` is left as-is (lets a re-run resume).
    """
    if skip_existing and Path(dst).exists() and Path(dst).stat().st_size > 0:
        return dst
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    vf = f"scale=-2:'min(ih,{height})'"

    encoder = hardware_encoder(ffmpeg_bin)
    software = ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf)]
    if encoder:
        # Hardware encoders use a target bitrate rather than CRF. ~2.5 Mbps at
        # 720p is plenty for talking-head footage; scale with frame height.
        target = bitrate or f"{max(800, round(2500 * height / 720))}k"
        attempts = [["-c:v", encoder, "-b:v", target], software]
    else:
        attempts = [software]

    def run(video_args: list[str]) -> None:
        subprocess.run(
            [
                ffmpeg_bin, "-y", "-i", src, "-vf", vf,
                *video_args, "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst,
            ],
            capture_output=True, check=True,
        )

    last: subprocess.CalledProcessError | None = None
    for video_args in attempts:  # try hardware, then fall back to software
        try:
            run(video_args)
            return dst
        except subprocess.CalledProcessError as exc:
            last = exc
    raise last  # type: ignore[misc]


def folder_total_bytes(folder: str) -> int:
    return sum(Path(p).stat().st_size for p in list_videos(folder))


def compress_folder(
    in_dir: str,
    out_dir: str,
    height: int = 720,
    crf: int = 28,
    ffmpeg_bin: str = "ffmpeg",
    skip_existing: bool = True,
    on_progress=None,
) -> list[str]:
    """Compress every video in `in_dir` into `out_dir`. Returns the proxy paths.

    `on_progress(message, fraction)` is called before each file if provided.
    """
    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    videos = list_videos(in_dir)
    proxies: list[str] = []
    n = len(videos)
    for i, src in enumerate(videos):
        name = Path(src).name
        if on_progress:
            on_progress(f"Compressing {i + 1} of {n}: {name}…", i / max(n, 1))
        dst = str(out / (Path(src).stem + ".mp4"))
        compress_video(src, dst, height, crf, ffmpeg_bin, skip_existing=skip_existing)
        proxies.append(dst)
    return proxies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="groupthink.compress",
        description="Batch-shrink videos before analyzing them with GroupThink.",
    )
    parser.add_argument("--in", dest="in_dir", required=True, help="Folder of source videos.")
    parser.add_argument("--out", dest="out_dir", required=True, help="Where to write the smaller copies.")
    parser.add_argument("--height", type=int, default=720, help="Max output height in pixels (default 720).")
    parser.add_argument("--crf", type=int, default=28, help="Software-encode quality 18-32; lower = better/bigger (default 28).")
    parser.add_argument("--bitrate", default=None, help="Hardware-encode target bitrate, e.g. 2500k (auto if omitted).")
    args = parser.parse_args(argv)

    settings = load_settings()
    videos = list_videos(args.in_dir)
    if not videos:
        parser.error(f"No videos found in {args.in_dir}")

    encoder = hardware_encoder(settings.ffmpeg_bin) or "libx264 (software)"
    print(f"Compressing {len(videos)} video(s) → {args.out_dir}  (≤{args.height}px tall, encoder: {encoder})\n")
    total_in = total_out = 0
    for i, src in enumerate(videos, start=1):
        name = Path(src).name
        print(f"  [{i}/{len(videos)}] {name} …", end=" ", flush=True)
        dst = str(Path(args.out_dir).expanduser() / (Path(src).stem + ".mp4"))
        try:
            compress_video(src, dst, args.height, args.crf, settings.ffmpeg_bin, bitrate=args.bitrate)
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
