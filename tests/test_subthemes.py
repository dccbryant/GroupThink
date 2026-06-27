from groupthink.analysis import resolve_report
from groupthink.assembly import timeline
from groupthink.assembly.document import build_doc_html
from groupthink.models import (
    AnalysisResult,
    QuoteSelection,
    SubThemeDraft,
    ThemeDraft,
)
from groupthink.transcription.mock import MockTranscriber


def _transcripts():
    t = MockTranscriber()
    return [t.transcribe("s1.mp4", "S1", "s1.mp4"), t.transcribe("s2.mp4", "S2", "s2.mp4")]


def _analysis_with_subthemes(transcripts):
    uids = [u.uid for u in transcripts[0].utterances]
    return AnalysisResult(themes=[
        ThemeDraft(
            title="Distrust of US healthcare system",
            summary="Respondents were sceptical of the system.",
            subthemes=[
                SubThemeDraft(title="Too much bureaucracy",
                              quotes=[QuoteSelection(utterance_id=uids[0], quote="x", rationale="r")]),
                SubThemeDraft(title="Sick care vs health care",
                              quotes=[QuoteSelection(utterance_id=uids[1], quote="x", rationale="r")]),
            ],
        )
    ])


def test_resolve_populates_subthemes():
    transcripts = _transcripts()
    report = resolve_report(_analysis_with_subthemes(transcripts), transcripts, "Study")
    assert len(report.themes) == 1
    theme = report.themes[0]
    assert [s.title for s in theme.subthemes] == ["Too much bureaucracy", "Sick care vs health care"]
    assert len(theme.all_quotes()) == 2  # one per sub-theme
    assert theme.quotes == []  # no flat quotes


def test_resolve_drops_subtheme_with_no_resolvable_quotes():
    transcripts = _transcripts()
    analysis = AnalysisResult(themes=[
        ThemeDraft(title="Topic", summary="s", subthemes=[
            SubThemeDraft(title="Ghost", quotes=[QuoteSelection(utterance_id="S9-9999", quote="x", rationale="r")]),
        ])
    ])
    report = resolve_report(analysis, transcripts, "Study")
    assert report.themes == []  # nothing resolvable -> theme dropped


def test_edl_and_doc_include_subtheme_titles():
    transcripts = _transcripts()
    report = resolve_report(_analysis_with_subthemes(transcripts), transcripts, "Study")
    edl = timeline.build_edl(report)
    assert "* TITLE CARD: Distrust of US healthcare system" in edl
    assert "* TITLE CARD: Too much bureaucracy" in edl  # sub-theme card present
    html = build_doc_html(report)
    assert "Distrust of US healthcare system" in html
    assert "Too much bureaucracy" in html
