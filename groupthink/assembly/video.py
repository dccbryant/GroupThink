"""Render an approved ThemeReport into a rough-cut MP4 with ffmpeg.

Each theme gets a title card, followed by its supporting quote clips cut from the
source videos. Every segment is re-encoded to identical parameters (1080p / 30fps
/ stereo AAC) so they concatenate cleanly even when the sources differ.

This is intentionally a *rough cut* — for a polished result the editable timeline
exports (see timeline.py) are the better handoff. Rendering is the slow,
expensive step, which is why the pipeline only does it after a report is approved.
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

from ..config import Settings
from ..models import ThemeReport

# Uniform target format for every segment.
_W, _H = 1920, 1080
_VF = (
    f"scale={_W}:{_H}:force_original_aspect_ratio=decrease,"
    f"pad={_W}:{_H}:(ow-iw)/2:(oh-ih)/2,setsar=1"
)

# Symbol / emoji / decorative fonts that look like ".ttf" but can't render plain
# text — picking one of these makes ffmpeg's drawtext fail (exit 8).
_BAD_FONT_HINTS = (
    "symbol", "wingding", "webding", "dingbat", "emoji", "bodoni ornaments",
    "apple color", "notocoloremoji", "applesymbols", "lastresort",
)

# Known-good text fonts by platform, in priority order.
_FONT_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Verdana.ttf",
    "/System/Library/Fonts/Geneva.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)


def _find_font() -> str | None:
    """Pick a font that can actually render text.

    Prefer a curated list of known-good text fonts; only fall back to a glob if
    none are present, and skip symbol/emoji fonts in that fallback.
    """
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    for pattern in (
        "/usr/share/fonts/**/DejaVu*Sans.ttf",
        "/usr/share/fonts/**/*.ttf",
        "/System/Library/Fonts/**/*.tt[cf]",
        "/Library/Fonts/**/*.tt[cf]",
        "C:/Windows/Fonts/*.ttf",
    ):
        for hit in sorted(glob.glob(pattern, recursive=True)):
            if not any(bad in os.path.basename(hit).lower() for bad in _BAD_FONT_HINTS):
                return hit
    return None


def _encode_args(fps: int) -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-ar", "48000", "-ac", "2",
        "-video_track_timescale", "30000",
    ]


def render_title_card(
    text: str,
    out_path: str,
    settings: Settings,
    seconds: float | None = None,
) -> str:
    """Render a centered-title card on a dark background with silent audio.

    Tries the chosen font, then ffmpeg's default font, and finally a plain card
    with no text — so a font problem on one machine can never kill a render.
    """
    seconds = settings.title_card_seconds if seconds is None else seconds
    fps = settings.render_fps
    font = _find_font()

    # Use drawtext's textfile= to sidestep all the filter-escaping pain.
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(text)
        textfile = tf.name

    base_draw = (
        f"drawtext=textfile='{textfile}':fontcolor=white:fontsize=72:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=16"
    )
    inputs = [
        "-f", "lavfi", "-i", f"color=c=0x111418:s={_W}x{_H}:d={seconds}:r={fps}",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]

    # Progressive fallbacks: best font -> default font -> no text at all.
    video_filters: list[str | None] = []
    if font:
        video_filters.append(base_draw + f":fontfile='{font}'")
    video_filters.append(base_draw)  # let ffmpeg/fontconfig choose a default font
    video_filters.append(None)       # plain card, no drawtext

    try:
        last_error: subprocess.CalledProcessError | None = None
        for vf in video_filters:
            cmd = [settings.ffmpeg_bin, "-y", *inputs]
            if vf is not None:
                cmd += ["-vf", vf]
            cmd += ["-t", str(seconds), *_encode_args(fps), out_path]
            try:
                subprocess.run(cmd, capture_output=True, check=True)
                return out_path
            except subprocess.CalledProcessError as exc:
                last_error = exc
        # All attempts failed (very unlikely — the last has no font at all).
        raise last_error  # type: ignore[misc]
    finally:
        Path(textfile).unlink(missing_ok=True)


def render_clip(
    source_video: str,
    start_ms: int,
    end_ms: int,
    out_path: str,
    settings: Settings,
) -> str:
    """Cut [start, end] from a source video, normalized to the target format."""
    fps = settings.render_fps
    start_s = start_ms / 1000.0
    duration_s = max(0.1, (end_ms - start_ms) / 1000.0)
    cmd = [
        settings.ffmpeg_bin, "-y",
        "-ss", f"{start_s:.3f}",
        "-i", source_video,
        "-t", f"{duration_s:.3f}",
        "-vf", _VF,
        *_encode_args(fps),
        out_path,
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return out_path


def render_report(
    report: ThemeReport,
    out_dir: str,
    settings: Settings,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> str:
    """Render the full themed reel. Returns the path to the final MP4."""
    out_dir_path = Path(out_dir)
    segments_dir = out_dir_path / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    # One segment per title card + one per quote, plus a final concat step.
    total_steps = sum(1 + len(t.quotes) for t in report.themes) + 1
    done = 0

    def step(message: str) -> None:
        nonlocal done
        if on_progress:
            # Reserve the first 5% for the timeline writing in pipeline.render.
            on_progress(message, 0.05 + 0.95 * (done / total_steps))
        done += 1

    segment_paths: list[Path] = []
    seq = 0
    for theme in report.themes:
        step(f"Rendering title card: {theme.title}")
        card = segments_dir / f"{seq:03d}_title.mp4"
        render_title_card(theme.title, str(card), settings)
        segment_paths.append(card)
        seq += 1

        for q_index, quote in enumerate(theme.quotes, start=1):
            step(f"Cutting clip {q_index} of {len(theme.quotes)} for “{theme.title}”…")
            clip = segments_dir / f"{seq:03d}_clip.mp4"
            render_clip(quote.source_video, quote.start_ms, quote.end_ms, str(clip), settings)
            segment_paths.append(clip)
            seq += 1

    if not segment_paths:
        raise RuntimeError("Nothing to render — the report has no resolvable quotes.")

    step("Stitching the reel together…")

    # Concatenate via the concat demuxer. Segments share an encode profile, so a
    # stream copy is safe and fast.
    list_file = out_dir_path / "concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in segment_paths)
    )
    final_path = out_dir_path / "highlight_reel.mp4"
    subprocess.run(
        [
            settings.ffmpeg_bin, "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy",
            str(final_path),
        ],
        capture_output=True,
        check=True,
    )
    return str(final_path)
