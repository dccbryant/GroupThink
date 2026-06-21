"""Editable timeline exports: CMX3600 EDL and FCPXML.

These let an editor open the auto-assembled cut in Premiere, DaVinci Resolve, or
Final Cut and refine it, rather than re-finding every clip by hand. The EDL is
the most portable; the FCPXML carries title-card and clip-name metadata that the
EDL format can't.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from ..models import ThemeReport, ms_to_timecode

TITLE_CARD_MS = 3000


def _reel_name(source_video: str) -> str:
    """An <=8 char, alphanumeric reel name derived from the source filename."""
    stem = Path(source_video).stem.upper()
    cleaned = re.sub(r"[^A-Z0-9]", "", stem)
    return (cleaned or "SOURCE")[:8]


def build_edl(report: ThemeReport, fps: int = 30, title_card_ms: int = TITLE_CARD_MS) -> str:
    """Render a CMX3600 EDL. Record timecodes run continuously from 00:00:00:00.

    Title cards are emitted as black-slug events (reel ``BL``) so the theme
    structure survives the round trip; most NLEs let you swap these for a real
    title generator on import.
    """
    lines = [f"TITLE: {report.project}", "FCM: NON-DROP FRAME", ""]
    event = 1
    record_ms = 0

    def tc(ms: int) -> str:
        return ms_to_timecode(ms, fps)

    def title_event(label: str) -> None:
        nonlocal event, record_ms
        lines.append(
            f"{event:03d}  BL       V     C        "
            f"{tc(0)} {tc(title_card_ms)} {tc(record_ms)} {tc(record_ms + title_card_ms)}"
        )
        lines.append(f"* TITLE CARD: {label}")
        lines.append("")
        record_ms += title_card_ms
        event += 1

    # Opening card with the research video title.
    title_event(report.display_title)

    for theme in report.themes:
        title_event(theme.title)

        for quote in theme.quotes:
            duration = quote.duration_ms
            reel = _reel_name(quote.source_video)
            lines.append(
                f"{event:03d}  {reel:<8} AA/V  C        "
                f"{tc(quote.start_ms)} {tc(quote.end_ms)} "
                f"{tc(record_ms)} {tc(record_ms + duration)}"
            )
            lines.append(f"* FROM CLIP NAME: {Path(quote.source_video).name}")
            lines.append(f"* QUOTE ({quote.speaker}): {quote.quote}")
            lines.append("")
            record_ms += duration
            event += 1

    return "\n".join(lines) + "\n"


def _fcp_duration(ms: int, fps: int) -> str:
    """FCPXML rational time, e.g. 90 frames at 30fps -> '90/30s'."""
    frames = round(ms / 1000 * fps)
    return f"{frames}/{fps}s"


def build_fcpxml(report: ThemeReport, fps: int = 30, title_card_ms: int = TITLE_CARD_MS) -> str:
    """Render an FCPXML (v1.10) project with one asset per source video.

    Title cards are represented as ``title`` elements; quotes as clip references
    into the source assets, laid end to end on the spine.
    """
    # One asset + format per distinct source video.
    sources = []
    seen: set[str] = set()
    for theme in report.themes:
        for quote in theme.quotes:
            if quote.source_video not in seen:
                seen.add(quote.source_video)
                sources.append(quote.source_video)

    fmt_id = "r1"
    asset_format = (
        f'<format id="{fmt_id}" name="FFVideoFormat1080p{fps}" '
        f'frameDuration="1/{fps}s" width="1920" height="1080"/>'
    )

    asset_defs = []
    asset_ids: dict[str, str] = {}
    for i, src in enumerate(sources, start=1):
        asset_id = f"a{i}"
        asset_ids[src] = asset_id
        name = html.escape(Path(src).stem)
        url = "file://" + html.escape(str(Path(src).resolve()))
        asset_defs.append(
            f'<asset id="{asset_id}" name="{name}" start="0s" hasVideo="1" hasAudio="1" '
            f'format="{fmt_id}" src="{url}"/>'
        )

    # Build the spine.
    title_dur = _fcp_duration(title_card_ms, fps)
    spine_items = []
    offset_ms = 0

    def title_item(label: str) -> None:
        nonlocal offset_ms
        spine_items.append(
            f'<title name="{html.escape(label)}" lane="0" '
            f'offset="{_fcp_duration(offset_ms, fps)}" duration="{title_dur}">'
            f'<text><text-style>{html.escape(label)}</text-style></text></title>'
        )
        offset_ms += title_card_ms

    # Opening card with the research video title.
    title_item(report.display_title)

    for theme in report.themes:
        title_item(theme.title)

        for quote in theme.quotes:
            asset_id = asset_ids[quote.source_video]
            spine_items.append(
                f'<asset-clip name="{html.escape(quote.speaker)}" ref="{asset_id}" '
                f'offset="{_fcp_duration(offset_ms, fps)}" '
                f'start="{_fcp_duration(quote.start_ms, fps)}" '
                f'duration="{_fcp_duration(quote.duration_ms, fps)}" format="{fmt_id}">'
                f"<note>{html.escape(quote.quote)}</note></asset-clip>"
            )
            offset_ms += quote.duration_ms

    total = _fcp_duration(offset_ms, fps)
    project_name = html.escape(report.project)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE fcpxml>
<fcpxml version="1.10">
  <resources>
    {asset_format}
    {"".join(asset_defs)}
  </resources>
  <library>
    <event name="{project_name}">
      <project name="{project_name}">
        <sequence format="{fmt_id}" duration="{total}">
          <spine>
            {"".join(spine_items)}
          </spine>
        </sequence>
      </project>
    </event>
  </library>
</fcpxml>
"""
