import pytest

from groupthink import pipeline
from groupthink.config import load_settings
from groupthink.models import Transcript, Utterance


class FlakyMock:
    """A 'mock'-named transcriber that fails on files whose name contains 'bad'."""

    name = "mock"  # mock branch skips ffmpeg, so no real media needed

    def transcribe(self, src, session_id, video):
        if "bad" in src:
            raise RuntimeError("language_detection cannot be performed on files with no spoken audio")
        return Transcript(
            session_id=session_id, source_video=video, duration_ms=1000,
            utterances=[Utterance(uid=f"{session_id}-0000", speaker="Speaker A",
                                  text="hello there", start_ms=0, end_ms=1000)],
        )


def test_bad_file_is_skipped_not_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "build_transcriber", lambda s: FlakyMock())
    warnings: list[str] = []
    transcripts = pipeline.transcribe_sessions(
        ["good1.mp4", "bad2.mp4", "good3.mp4"], load_settings(), str(tmp_path), warnings=warnings
    )
    assert len(transcripts) == 2  # the two good files survive
    assert warnings and "Skipped 1 of 3" in warnings[0]
    assert "bad2.mp4" in warnings[0]


def test_all_bad_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "build_transcriber", lambda s: FlakyMock())
    with pytest.raises(RuntimeError):
        pipeline.transcribe_sessions(["bad1.mp4", "bad2.mp4"], load_settings(), str(tmp_path), warnings=[])
