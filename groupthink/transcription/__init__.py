"""Stage 2 — transcription + diarization.

Each backend implements `Transcriber.transcribe(...)` and returns a
`Transcript` with diarized, timecoded utterances.
"""

from __future__ import annotations

from ..config import Settings
from .base import Transcriber
from .mock import MockTranscriber


def build_transcriber(settings: Settings) -> Transcriber:
    """Pick a transcription backend based on configuration and available keys.

    Falls back to the mock backend when AssemblyAI is requested but no key is
    present, so a fresh checkout runs end-to-end without credentials.
    """
    provider = settings.asr_provider.lower()
    if provider == "assemblyai" and settings.has_assemblyai:
        from .assemblyai import AssemblyAITranscriber

        return AssemblyAITranscriber(settings.assemblyai_api_key, settings.asr_language)
    return MockTranscriber()


__all__ = ["Transcriber", "MockTranscriber", "build_transcriber"]
