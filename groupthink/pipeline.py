"""Orchestrates the four stages end to end.

Typical flow:
    analyze_sessions(videos)  -> (transcripts, ThemeReport)   # fast, reviewable
    # ... human reviews / edits the ThemeReport ...
    render(report)            -> MP4 + EDL + FCPXML            # slow, on approval
"""

from __future__ import annotations

import json
from pathlib import Path

from .analysis import build_analyzer, resolve_report
from .assembly import timeline, video
from .audio import extract_audio, probe_duration_ms
from .config import Settings, load_settings
from .models import ThemeReport, Transcript
from .transcription import build_transcriber


def transcribe_sessions(
    videos: list[str],
    settings: Settings,
    work_dir: str,
) -> list[Transcript]:
    """Stages 1-2: extract audio and transcribe each video into a Transcript."""
    transcriber = build_transcriber(settings)
    audio_dir = Path(work_dir) / "audio"
    transcripts: list[Transcript] = []

    for i, video_path in enumerate(videos, start=1):
        session_id = f"S{i}"
        # Mock transcription doesn't need real audio; skip ffmpeg if the source
        # isn't a readable media file (keeps unit tests and demos fast).
        if transcriber.name == "mock":
            transcript = transcriber.transcribe(video_path, session_id, video_path)
        else:
            audio_path = extract_audio(video_path, str(audio_dir), settings.ffmpeg_bin)
            transcript = transcriber.transcribe(audio_path, session_id, video_path)
            if not transcript.duration_ms:
                transcript.duration_ms = probe_duration_ms(video_path, settings.ffprobe_bin)
        transcripts.append(transcript)

    return transcripts


def analyze_sessions(
    videos: list[str],
    project: str,
    settings: Settings | None = None,
    work_dir: str | None = None,
) -> tuple[list[Transcript], ThemeReport]:
    """Stages 1-3: produce the reviewable ThemeReport (no rendering)."""
    settings = settings or load_settings()
    work_dir = work_dir or settings.work_dir

    transcripts = transcribe_sessions(videos, settings, work_dir)
    analyzer = build_analyzer(settings)
    analysis = analyzer.analyze(transcripts, project)
    report = resolve_report(analysis, transcripts, project)
    return transcripts, report


def render(
    report: ThemeReport,
    out_dir: str,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Stage 4: render MP4 + editable timelines. Returns paths by artifact name."""
    settings = settings or load_settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    report_json = out / "report.json"
    report_json.write_text(json.dumps(report.model_dump(), indent=2))

    edl_path = out / "report.edl"
    edl_path.write_text(timeline.build_edl(report, settings.render_fps))

    fcpxml_path = out / "report.fcpxml"
    fcpxml_path.write_text(timeline.build_fcpxml(report, settings.render_fps))

    mp4_path = video.render_report(report, str(out), settings)

    return {
        "mp4": mp4_path,
        "edl": str(edl_path),
        "fcpxml": str(fcpxml_path),
        "report_json": str(report_json),
    }
