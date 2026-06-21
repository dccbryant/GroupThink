"""Mock backend — a deterministic, diarized transcript with no network or keys.

This lets the whole pipeline (analysis, review, render, timeline export) and the
web UI run end-to-end on a fresh checkout. The canned content is written to look
like a real focus group so the theme-finding step has something meaningful to
chew on.
"""

from __future__ import annotations

from ..models import Transcript, Utterance
from .base import make_uid

# A small bank of focus-group-style lines, grouped loosely by latent theme so
# the analysis stage finds something coherent. Each session draws a rotated
# slice of these.
_LINES: list[tuple[str, str]] = [
    ("A", "Honestly the price is the first thing that jumps out at me, it feels high for what you get."),
    ("B", "I'd pay it if I trusted the brand more, but I've never heard of them before today."),
    ("A", "The packaging looks premium though, that part I really liked."),
    ("C", "For me it's all about whether it actually saves time in the morning."),
    ("B", "Right, if it shaves ten minutes off my routine then the price stops mattering."),
    ("C", "I don't trust the claims on the box, they feel exaggerated."),
    ("A", "My kids would never use it, it looks too complicated to set up."),
    ("B", "Setup is my worry too, I don't want to read a manual for this."),
    ("C", "The design is gorgeous, I'd leave it on the counter happily."),
    ("A", "If a friend recommended it I'd buy it tomorrow, word of mouth is everything."),
    ("B", "I'd want to see reviews first, lots of them, before I spend that much."),
    ("C", "It comes down to trust for me, I need to believe it'll last."),
]


class MockTranscriber:
    name = "mock"

    def transcribe(self, audio_path: str, session_id: str, source_video: str) -> Transcript:
        # Rotate the line bank by a stable offset per session so the sessions
        # differ but still share themes.
        offset = (abs(hash(session_id)) % len(_LINES))
        ordered = _LINES[offset:] + _LINES[:offset]

        utterances: list[Utterance] = []
        cursor_ms = 2_000  # leave a little room at the head
        for index, (speaker, text) in enumerate(ordered):
            # ~80ms per character is a natural-sounding speaking rate.
            duration_ms = max(2_500, len(text) * 80)
            utterances.append(
                Utterance(
                    uid=make_uid(session_id, index),
                    speaker=f"Speaker {speaker}",
                    text=text,
                    start_ms=cursor_ms,
                    end_ms=cursor_ms + duration_ms,
                )
            )
            cursor_ms += duration_ms + 600  # small gap between turns

        return Transcript(
            session_id=session_id,
            source_video=source_video,
            duration_ms=cursor_ms,
            utterances=utterances,
        )
