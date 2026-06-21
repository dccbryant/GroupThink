"""Stage 1 — pull an audio track out of a session video with ffmpeg."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe_duration_ms(video_path: str, ffprobe_bin: str = "ffprobe") -> int:
    """Return the media duration in milliseconds, or 0 if it can't be read."""
    try:
        out = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = json.loads(out.stdout)["format"]["duration"]
        return int(float(duration) * 1000)
    except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError):
        return 0


def extract_audio(
    video_path: str,
    out_dir: str,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Extract a 16 kHz mono WAV — the format transcription services prefer.

    Returns the path to the written audio file.
    """
    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir_path / (Path(video_path).stem + ".wav")

    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-i",
            video_path,
            "-vn",  # drop video
            "-ac",
            "1",  # mono
            "-ar",
            "16000",  # 16 kHz
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ],
        capture_output=True,
        check=True,
    )
    return str(audio_path)
