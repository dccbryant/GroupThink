"""AssemblyAI backend — strong speaker diarization with word-level timecodes.

AssemblyAI's ``speaker_labels`` returns utterances already grouped by speaker
turn, each with start/end in milliseconds — exactly the shape we need, so this
adapter is thin.
"""

from __future__ import annotations

from ..models import Transcript, Utterance
from .base import make_uid


class AssemblyAITranscriber:
    name = "assemblyai"

    def __init__(self, api_key: str) -> None:
        import assemblyai as aai

        aai.settings.api_key = api_key
        self._aai = aai

    def transcribe(self, audio_path: str, session_id: str, source_video: str) -> Transcript:
        aai = self._aai
        config = aai.TranscriptionConfig(speaker_labels=True)
        result = aai.Transcriber().transcribe(audio_path, config=config)

        if result.status == aai.TranscriptStatus.error:
            raise RuntimeError(f"AssemblyAI transcription failed: {result.error}")

        utterances: list[Utterance] = []
        # `result.utterances` are diarized speaker turns with ms timecodes.
        for index, turn in enumerate(result.utterances or []):
            utterances.append(
                Utterance(
                    uid=make_uid(session_id, index),
                    speaker=f"Speaker {turn.speaker}",
                    text=turn.text.strip(),
                    start_ms=int(turn.start),
                    end_ms=int(turn.end),
                )
            )

        duration_ms = utterances[-1].end_ms if utterances else 0
        return Transcript(
            session_id=session_id,
            source_video=source_video,
            duration_ms=duration_ms,
            utterances=utterances,
        )
