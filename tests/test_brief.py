from groupthink.analysis import render_brief
from groupthink.models import AnalysisBrief


def test_empty_brief_renders_nothing():
    assert render_brief(None) == ""
    assert render_brief(AnalysisBrief()) == ""


def test_restrict_wording():
    out = render_brief(AnalysisBrief(topics="Price\nTrust", restrict_to_topics=True))
    assert "ONLY within these topics" in out or "ONLY" in out
    assert "Price" in out and "Trust" in out


def test_non_restrict_also_surfaces_others():
    out = render_brief(AnalysisBrief(topics="Price", restrict_to_topics=False))
    assert "also surface" in out.lower()
    assert "Price" in out


def test_discussion_guide_included():
    out = render_brief(AnalysisBrief(discussion_guide="Q1: How did you feel about price?"))
    assert "DISCUSSION GUIDE" in out
    assert "Q1: How did you feel about price?" in out
