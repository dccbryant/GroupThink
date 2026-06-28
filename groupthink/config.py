"""Runtime configuration.

API keys come from the environment (or the in-app key store layered on top by
the web app). Binary paths and the work directory are resolved with bundle
awareness so the same code path serves both the source checkout and the
packaged macOS desktop app.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .runtime import app_support_dir, find_binary, is_frozen


def _default_work_dir() -> str:
    """Pick a sensible work directory.

    Frozen .app: per-user Application Support folder (writable, persistent).
    Source: a ``./workspace`` folder next to wherever the user launched it.
    Either is overridable via ``GROUPTHINK_WORK_DIR``.
    """
    override = os.getenv("GROUPTHINK_WORK_DIR")
    if override:
        return override
    if is_frozen():
        return str(app_support_dir() / "workspace")
    return "./workspace"


@dataclass(frozen=True)
class Settings:
    # Which speech-to-text backend to use: "assemblyai" (real, diarized) or
    # "mock" (no network/keys — generates a deterministic fake transcript so the
    # rest of the pipeline and the web UI can be exercised end to end).
    asr_provider: str = os.getenv("ASR_PROVIDER", "assemblyai")
    assemblyai_api_key: str | None = os.getenv("ASSEMBLYAI_API_KEY")
    # Optional fixed language (e.g. "en"). When unset, the language is
    # auto-detected per file — which errors on silent clips, so set this if all
    # your sessions are one known language.
    asr_language: str | None = os.getenv("ASR_LANGUAGE")

    # Claude (theme analysis). claude-opus-4-8 is the strongest model and this
    # is the judgement-heavy step, so it is the default.
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    analysis_model: str = os.getenv("ANALYSIS_MODEL", "claude-opus-4-8")

    # Video rendering. find_binary() resolves to the bundled ffmpeg/ffprobe when
    # frozen, falling through to PATH and Homebrew locations otherwise.
    ffmpeg_bin: str = field(default_factory=lambda: find_binary("ffmpeg"))
    ffprobe_bin: str = field(default_factory=lambda: find_binary("ffprobe"))
    render_fps: int = int(os.getenv("RENDER_FPS", "30"))
    title_card_seconds: float = float(os.getenv("TITLE_CARD_SECONDS", "3.0"))

    # Where uploads and renders are written.
    work_dir: str = field(default_factory=_default_work_dir)

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_assemblyai(self) -> bool:
        return bool(self.assemblyai_api_key)


def load_settings() -> Settings:
    return Settings()
