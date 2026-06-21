"""Runtime configuration, resolved from environment variables.

Nothing here is secret-bearing on its own — API keys are read from the
environment at call time and never written to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Which speech-to-text backend to use: "assemblyai" (real, diarized) or
    # "mock" (no network/keys — generates a deterministic fake transcript so the
    # rest of the pipeline and the web UI can be exercised end to end).
    asr_provider: str = os.getenv("ASR_PROVIDER", "assemblyai")
    assemblyai_api_key: str | None = os.getenv("ASSEMBLYAI_API_KEY")

    # Claude (theme analysis). claude-opus-4-8 is the strongest model and this
    # is the judgement-heavy step, so it is the default.
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    analysis_model: str = os.getenv("ANALYSIS_MODEL", "claude-opus-4-8")

    # When mock mode is on for analysis too (no Anthropic key), the pipeline
    # falls back to a naive keyword grouping so the demo still produces themes.
    # This is set automatically in pipeline.py based on key availability.

    # Video rendering
    ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")
    ffprobe_bin: str = os.getenv("FFPROBE_BIN", "ffprobe")
    render_fps: int = int(os.getenv("RENDER_FPS", "30"))
    title_card_seconds: float = float(os.getenv("TITLE_CARD_SECONDS", "3.0"))

    # Where uploads and renders are written.
    work_dir: str = os.getenv("GROUPTHINK_WORK_DIR", "./workspace")

    # Offer in-app compression when a selected folder exceeds this many GB.
    compress_threshold_gb: float = float(os.getenv("COMPRESS_THRESHOLD_GB", "20"))

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_assemblyai(self) -> bool:
        return bool(self.assemblyai_api_key)


def load_settings() -> Settings:
    return Settings()
