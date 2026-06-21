"""GroupThink — turn raw focus-group footage into a themed highlight reel.

Pipeline stages (see groupthink/pipeline.py):
    1. audio        extract an audio track from each session video (ffmpeg)
    2. transcription transcribe + diarize with word/utterance timecodes
    3. analysis     Claude finds cross-session themes and selects supporting quotes
    4. assembly     cut the quote clips, build title cards, render MP4 + timeline
"""

__version__ = "0.1.0"
