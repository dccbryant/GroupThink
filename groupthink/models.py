"""Data models shared across the pipeline.

These Pydantic models are the contract between stages. The transcription stage
produces a `Transcript`; the analysis stage consumes transcripts and produces a
`ThemeReport`; the assembly stage consumes a resolved `ThemeReport` to render
video and timelines.

A note on timecodes: everything is stored in **milliseconds** (integers) to
avoid float drift when seeking with ffmpeg.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


def ms_to_timecode(ms: int, fps: int = 30) -> str:
    """Render milliseconds as an EDL/FCP-style HH:MM:SS:FF timecode."""
    total_seconds, remainder_ms = divmod(int(ms), 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    frames = int(remainder_ms / 1000 * fps)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def ms_to_seconds(ms: int) -> float:
    return round(int(ms) / 1000.0, 3)


# --------------------------------------------------------------------------- #
# Transcription output
# --------------------------------------------------------------------------- #


class Utterance(BaseModel):
    """A single continuous span of speech by one speaker.

    `uid` is a stable, human-readable identifier (e.g. ``S1-0042``) that we hand
    to Claude so it can reference quotes without ever inventing a timecode.
    """

    uid: str
    speaker: str
    text: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class Transcript(BaseModel):
    """All speech for one session video."""

    session_id: str
    source_video: str
    duration_ms: int = 0
    utterances: list[Utterance] = Field(default_factory=list)

    def get(self, uid: str) -> Utterance | None:
        for u in self.utterances:
            if u.uid == uid:
                return u
        return None


# --------------------------------------------------------------------------- #
# Analysis output (what Claude returns — see analysis.py)
# --------------------------------------------------------------------------- #


class QuoteSelection(BaseModel):
    """A quote Claude picked to support a theme, referenced by utterance id.

    Claude does NOT supply timecodes — it references `utterance_id` and we
    resolve the real start/end from the transcript. This makes hallucinated
    timecodes structurally impossible.
    """

    utterance_id: str = Field(
        description="The uid of the supporting utterance, exactly as shown in the transcript (e.g. 'S2-0031')."
    )
    quote: str = Field(
        description="The respondent's words for this quote, copied verbatim from the utterance text."
    )
    rationale: str = Field(
        description="One sentence on why this quote supports the theme."
    )


class ThemeDraft(BaseModel):
    """A theme as proposed by Claude, before timecode resolution."""

    title: str = Field(description="A short, presentable theme title (3-7 words).")
    summary: str = Field(
        description="One or two sentences describing the theme in the researcher's voice."
    )
    quotes: list[QuoteSelection] = Field(
        description="3-6 supporting quotes drawn from across the sessions."
    )


class AnalysisResult(BaseModel):
    """The full structured response we request from Claude."""

    themes: list[ThemeDraft]


# --------------------------------------------------------------------------- #
# Resolved report (analysis output joined back to real timecodes)
# --------------------------------------------------------------------------- #


class ResolvedQuote(BaseModel):
    """A quote with its source video and exact timecodes resolved."""

    session_id: str
    source_video: str
    speaker: str
    quote: str
    rationale: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


class ResolvedTheme(BaseModel):
    title: str
    summary: str
    quotes: list[ResolvedQuote]


class ThemeReport(BaseModel):
    """The reviewable deliverable: themes, quotes, and timecodes.

    This is what a researcher approves before any video is rendered.
    """

    project: str
    # On-screen title for the opening card. Falls back to `project` if unset.
    title: Optional[str] = None
    themes: list[ResolvedTheme]

    @property
    def display_title(self) -> str:
        return (self.title or "").strip() or self.project
