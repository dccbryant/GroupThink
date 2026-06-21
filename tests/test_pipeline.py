from groupthink.analysis import KeywordAnalyzer, resolve_report
from groupthink.models import AnalysisResult, QuoteSelection, ThemeDraft
from groupthink.transcription.mock import MockTranscriber


def _transcripts():
    t = MockTranscriber()
    return [
        t.transcribe("session_1.mp4", "S1", "session_1.mp4"),
        t.transcribe("session_2.mp4", "S2", "session_2.mp4"),
    ]


def test_mock_transcript_has_diarized_timecoded_utterances():
    [t1, _] = _transcripts()
    assert t1.utterances
    for u in t1.utterances:
        assert u.start_ms < u.end_ms
        assert u.speaker.startswith("Speaker ")
        assert u.uid.startswith("S1-")


def test_keyword_analyzer_and_resolution_roundtrip():
    transcripts = _transcripts()
    analysis = KeywordAnalyzer().analyze(transcripts, "Test")
    report = resolve_report(analysis, transcripts, "Test")
    assert report.themes
    for theme in report.themes:
        assert 1 <= len(theme.quotes) <= 6
        for q in theme.quotes:
            # Every resolved quote carries a real source + timecode.
            assert q.source_video.endswith(".mp4")
            assert q.end_ms > q.start_ms


def test_resolution_drops_unknown_utterance_ids():
    transcripts = _transcripts()
    analysis = AnalysisResult(
        themes=[
            ThemeDraft(
                title="Ghost theme",
                summary="references a non-existent utterance",
                quotes=[QuoteSelection(utterance_id="S9-9999", quote="nope", rationale="x")],
            )
        ]
    )
    report = resolve_report(analysis, transcripts, "Test")
    # Theme had only an unresolvable quote, so it is dropped entirely.
    assert report.themes == []
