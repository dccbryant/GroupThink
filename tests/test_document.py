import importlib.util

import pytest

from groupthink.assembly.document import build_doc_html, build_docx
from groupthink.models import ResolvedQuote, ResolvedTheme, ThemeReport


def _report():
    return ThemeReport(
        project="Snack Study",
        themes=[
            ResolvedTheme(
                title="Price and value",
                summary="People discussed price.",
                quotes=[
                    ResolvedQuote(
                        session_id="S1", source_video="/x/session_1.mp4",
                        speaker="Speaker A", quote="Too expensive.", rationale="price",
                        start_ms=42_000, end_ms=69_000,
                    )
                ],
            )
        ],
    )


def test_doc_html_contains_content_and_timecode():
    doc = build_doc_html(_report())
    assert "Snack Study" in doc
    assert "Price and value" in doc
    assert "Too expensive." in doc
    assert "0:42" in doc and "1:09" in doc  # mm:ss timecodes


def test_doc_html_escapes_markup():
    report = _report()
    report.themes[0].quotes[0].quote = "5 < 10 & <b>bold</b>"
    doc = build_doc_html(report)
    assert "<b>bold</b>" not in doc
    assert "&lt;b&gt;bold&lt;/b&gt;" in doc


@pytest.mark.skipif(
    importlib.util.find_spec("docx") is None, reason="python-docx not installed"
)
def test_docx_is_a_valid_zip_package():
    data = build_docx(_report())
    assert data[:2] == b"PK"  # .docx is a zip
