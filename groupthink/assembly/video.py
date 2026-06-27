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


# Left margin for flush-left titles (at 1920px wide).
_LEFT_MARGIN = 140
# Bundled font so titles render the same everywhere, regardless of system fonts
# or how the local ffmpeg was built.
_BUNDLED_FONT = Path(__file__).resolve().parent.parent / "assets" / "DejaVuSans.ttf"


def _load_pil_font(fontsize: int):
    """Load a TrueType font for Pillow, preferring the bundled one."""
    try:
        from PIL import ImageFont
    except Exception:
        return None
    for path in (str(_BUNDLED_FONT), *_FONT_CANDIDATES):
        try:
            return ImageFont.truetype(path, fontsize)
        except Exception:
            continue
    return None


def _wrap_lines(draw, text: str, font, max_width: int) -> list[str]:
    """Greedy word-wrap so long titles fit the frame width."""
    words = text.split()
    if not words:
        return [text]
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _make_title_png(text: str, png_path: str, fontsize: int) -> bool:
    """Draw the title onto a 1920x1080 black PNG. Returns True on success."""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return False
    font = _load_pil_font(fontsize)
    if font is None:
        return False
    img = Image.new("RGB", (_W, _H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    lines = _wrap_lines(draw, text, font, _W - 2 * _LEFT_MARGIN)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent + 18
    y = (_H - line_height * len(lines)) // 2
    for line in lines:
        draw.text((_LEFT_MARGIN, y), line, fill=(255, 255, 255), font=font)
        y += line_height
    img.save(png_path)
    return True


def render_title_card(
    text: str,
    out_path: str,
    settings: Settings,
    seconds: float | None = None,
    fontsize: int = 72,
) -> tuple[str, bool]:
    """Render a title card: white sans-serif text, flush left, vertically
    centered, on black, fading in/out, with silent audio.

    Text is drawn with Pillow into an image first (works on every machine), then
    laid over black by ffmpeg. If Pillow or a font is unavailable we fall back to
    ffmpeg's drawtext, and finally to a plain card with no text.

    Returns (path, text_drawn) so the caller can warn if a card ended up blank.
    """
    seconds = settings.title_card_seconds if seconds is None else seconds
    fps = settings.render_fps
    fade = f"fade=t=in:st=0:d=0.4,fade=t=out:st={max(0.0, seconds - 0.5):.2f}:d=0.5"
    silent = ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    color_in = ["-f", "lavfi", "-i", f"color=c=black:s={_W}x{_H}:d={seconds}:r={fps}"]

    # 1) Preferred: Pillow renders the text; ffmpeg just encodes the image.
    png_path = out_path + ".png"
    if _make_title_png(text, png_path, fontsize):
        try:
            subprocess.run(
                [
                    settings.ffmpeg_bin, "-y", "-loop", "1", "-i", png_path, *silent,
                    "-t", str(seconds), "-vf", f"{fade},format=yuv420p",
                    *_encode_args(fps), out_path,
                ],
                capture_output=True, check=True,
            )
            return out_path, True
        except subprocess.CalledProcessError:
            pass
        finally:
            Path(png_path).unlink(missing_ok=True)

    # 2) Fallback: ffmpeg drawtext (needs a freetype-enabled build + a font).
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tf:
        tf.write(text)
        textfile = tf.name
    base_draw = (
        f"drawtext=textfile='{textfile}':fontcolor=white:fontsize={fontsize}:"
        f"x={_LEFT_MARGIN}:y=(h-text_h)/2:line_spacing=18"
    )
    attempts = []
    font = _find_font()
    if font:
        attempts.append(f"{base_draw}:fontfile='{font}',{fade}")
    attempts.append(f"{base_draw},{fade}")
    try:
        for vf in attempts:
            try:
                subprocess.run(
                    [settings.ffmpeg_bin, "-y", *color_in, *silent, "-vf", vf,
                     "-t", str(seconds), *_encode_args(fps), out_path],
                    capture_output=True, check=True,
                )
                return out_path, True
            except subprocess.CalledProcessError:
                continue
    finally:
        Path(textfile).unlink(missing_ok=True)

    # 3) Last resort: a plain black card so the render still completes.
    subprocess.run(
        [settings.ffmpeg_bin, "-y", *color_in, *silent, "-vf", fade,
         "-t", str(seconds), *_encode_args(fps), out_path],
        capture_output=True, check=True,
    )
    return out_path, False


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
    warnings: Optional[list] = None,
) -> str:
    """Render the full themed reel. Returns the path to the final MP4.

    If any title card ends up blank (no usable text rendering), a message is
    appended to ``warnings`` so the caller can surface it.
    """
    out_dir_path = Path(out_dir)
    segments_dir = out_dir_path / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    # Opening card + per theme: a topic card, optional sub-theme cards, and a
    # card-or-clip per quote; plus a final concat.
    total_steps = 1 + 1
    for t in report.themes:
        total_steps += 1 + len(t.quotes)
        for sub in t.subthemes:
            total_steps += 1 + len(sub.quotes)
    done = 0
    all_text_ok = True

    def step(message: str) -> None:
        nonlocal done
        if on_progress:
            # Reserve the first 5% for the timeline writing in pipeline.render.
            on_progress(message, 0.05 + 0.95 * (done / total_steps))
        done += 1

    segment_paths: list[Path] = []
    seq = 0

    def add_title(text: str, fontsize: int) -> None:
        nonlocal seq, all_text_ok
        card = segments_dir / f"{seq:03d}_title.mp4"
        _, ok = render_title_card(text, str(card), settings, fontsize=fontsize)
        all_text_ok = all_text_ok and ok
        segment_paths.append(card)
        seq += 1

    def add_clip(quote) -> None:
        nonlocal seq
        clip = segments_dir / f"{seq:03d}_clip.mp4"
        render_clip(quote.source_video, quote.start_ms, quote.end_ms, str(clip), settings)
        segment_paths.append(clip)
        seq += 1

    # Opening card with the research video's title, set a little larger.
    step(f"Rendering opening title: {report.display_title}")
    add_title(report.display_title, fontsize=84)

    for theme in report.themes:
        step(f"Rendering title card: {theme.title}")
        add_title(theme.title, fontsize=72)

        for sub in theme.subthemes:
            step(f"Rendering sub-theme: {sub.title}")
            add_title(sub.title, fontsize=52)
            for quote in sub.quotes:
                step(f"Cutting clip for “{sub.title}”…")
                add_clip(quote)

        for q_index, quote in enumerate(theme.quotes, start=1):
            step(f"Cutting clip {q_index} of {len(theme.quotes)} for “{theme.title}”…")
            add_clip(quote)

    if not segment_paths:
        raise RuntimeError("Nothing to render — the report has no resolvable quotes.")

    if not all_text_ok and warnings is not None:
        warnings.append(
            "Title cards rendered without text — no usable font was available. "
            "Install Pillow (pip install pillow) to fix this; the title text will "
            "then appear on the next render."
        )

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
