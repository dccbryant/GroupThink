"""Transcriber protocol and a shared helper for building utterance ids."""

from __future__ import annotations

from typing import Protocol

from ..models import Transcript


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio_path: str, session_id: str, source_video: str) -> Transcript:
        """Transcribe one session's audio into a diarized `Transcript`."""
        ...


def make_uid(session_id: str, index: int) -> str:
    """Stable per-utterance id handed to Claude, e.g. ``S1-0042``.

    Using the session id keeps ids unique across the whole project so a single
    flat reference (the utterance id) is enough to resolve a quote back to its
    source video and timecode.
    """
    return f"{session_id}-{index:04d}"
