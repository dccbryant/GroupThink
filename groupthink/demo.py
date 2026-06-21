"""Generate synthetic 'session' videos so the whole pipeline can run offline.

Each demo video is a solid-colour 1080p clip with a test tone, long enough to
cover the mock transcript's timecodes. Combined with the mock transcriber and the
keyword analyzer, this lets `python -m groupthink.cli --demo` produce a real MP4
and timeline with no API keys, no ffmpeg input footage, and no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import Settings

_COLORS = ["0x1b3a4b", "0x3b1f2b", "0x21331f", "0x402d1a"]


def make_demo_videos(out_dir: str, settings: Settings, count: int = 3, seconds: int = 60) -> list[str]:
    """Create `count` synthetic session videos. Returns their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for i in range(count):
        color = _COLORS[i % len(_COLORS)]
        path = out / f"session_{i + 1}.mp4"
        subprocess.run(
            [
                settings.ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", f"color=c={color}:s=1280x720:d={seconds}:r={settings.render_fps}",
                "-f", "lavfi", "-i", f"sine=frequency={220 + i * 110}:duration={seconds}",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-ar", "48000", "-ac", "2",
                "-shortest",
                str(path),
            ],
            capture_output=True,
            check=True,
        )
        paths.append(str(path))
    return paths
