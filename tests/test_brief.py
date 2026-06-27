from groupthink.analysis import KeywordAnalyzer, parse_topics, render_brief
from groupthink.models import AnalysisBrief
from groupthink.transcription.mock import MockTranscriber


def test_empty_brief_renders_nothing():
    assert render_brief(None) == ""
    assert render_brief(AnalysisBrief()) == ""


def test_parse_topics_multiline_and_comma():
    assert parse_topics("Price\nTrust\nEase") == ["Price", "Trust", "Ease"]
    assert parse_topics("Price, Trust, Ease") == ["Price", "Trust", "Ease"]
    # multiline wins, so a comma inside a single line isn't split
    assert parse_topics("Price, value and cost\nTrust") == ["Price, value and cost", "Trust"]
    # bullet/number markers are stripped
    assert parse_topics("1. Price\n2) Trust\n- Ease") == ["Price", "Trust", "Ease"]


def test_restricted_uses_topics_as_titles_verbatim_in_order():
    out = render_brief(AnalysisBrief(topics="Price\nTrust", restrict_to_topics=True))
    assert "VERBATIM as a theme title" in out
    assert "SECTION TITLES" in out
    assert out.index("1. Price") < out.index("2. Trust")  # order preserved


def test_non_restrict_also_surfaces_others():
    out = render_brief(AnalysisBrief(topics="Price", restrict_to_topics=False))
    assert "also surface" in out.lower()
    assert "1. Price" in out


def test_discussion_guide_included():
    out = render_brief(AnalysisBrief(discussion_guide="Q1: How did you feel about price?"))
    assert "DISCUSSION GUIDE" in out
    assert "Q1: How did you feel about price?" in out


def test_keyword_fallback_titles_themes_by_topic_in_restricted_mode():
    t = MockTranscriber()
    transcripts = [t.transcribe("s1.mp4", "S1", "s1.mp4"), t.transcribe("s2.mp4", "S2", "s2.mp4")]
    brief = AnalysisBrief(topics="price\ntrust", restrict_to_topics=True)
    result = KeywordAnalyzer().analyze(transcripts, "Test", brief)
    titles = [th.title for th in result.themes]
    # Only the user's topics appear as titles (in order, where matched).
    assert titles and set(titles).issubset({"price", "trust"})
