import xml.dom.minidom as minidom

from groupthink.assembly import timeline
from groupthink.models import ResolvedQuote, ResolvedTheme, ThemeReport


def _report():
    return ThemeReport(
        project="Test Study",
        themes=[
            ResolvedTheme(
                title="Price and value",
                summary="People talked about price.",
                quotes=[
                    ResolvedQuote(
                        session_id="S1", source_video="/x/session_1.mp4",
                        speaker="Speaker A", quote="Too expensive.", rationale="price",
                        start_ms=42_000, end_ms=49_000,
                    ),
                    ResolvedQuote(
                        session_id="S2", source_video="/x/session_2.mp4",
                        speaker="Speaker B", quote="Worth it.", rationale="value",
                        start_ms=8_000, end_ms=14_000,
                    ),
                ],
            )
        ],
    )


def test_edl_has_opening_title_card():
    edl = timeline.build_edl(_report(), fps=30, title_card_ms=3000)
    # First card is the opening title (project name when no explicit title set).
    assert "* TITLE CARD: Test Study" in edl
    assert edl.index("* TITLE CARD: Test Study") < edl.index("* TITLE CARD: Price and value")


def test_edl_record_timecodes_are_continuous():
    edl = timeline.build_edl(_report(), fps=30, title_card_ms=3000)
    assert "TITLE: Test Study" in edl
    # Opening card (3s) + theme card (3s) + two clips (7s, 6s) => 19s record-out.
    assert "00:00:19:00" in edl
    # Source timecodes are preserved from the quotes.
    assert "00:00:42:00 00:00:49:00" in edl


def test_edl_reel_names_sanitized_and_short():
    edl = timeline.build_edl(_report())
    assert "SESSION1" in edl  # <=8 chars, alphanumeric
    assert "session_1.mp4" in edl  # full name preserved in the comment


def test_fcpxml_is_well_formed():
    xml = timeline.build_fcpxml(_report())
    # Raises if malformed.
    minidom.parseString(xml)
    assert "Price and value" in xml
    assert "asset-clip" in xml
