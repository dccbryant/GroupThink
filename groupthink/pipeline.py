"""Orchestrates the four stages end to end.

Typical flow:
    analyze_sessions(videos)  -> (transcripts, ThemeReport)   # fast, reviewable
    # ... human reviews / edits the ThemeReport ...
    render(report)            -> MP4 + EDL + FCPXML            # slow, on approval
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .analysis import build_analyzer, resolve_report
from .assembly import timeline, video
from .audio import extract_audio, probe_duration_ms
from .config import Settings, load_settings
from .models import ThemeReport, Transcript
from .transcription import build_transcriber

# A progress reporter: (human-readable message, fraction complete 0.0-1.0).
ProgressFn = Callable[[str, float], None]


def transcribe_sessions(
    videos: list[str],
    settings: Settings,
    work_dir: str,
    on_progress: Optional[ProgressFn] = None,
    warnings: Optional[list] = None,
) -> list[Transcript]:
    """Stages 1-2: extract audio and transcribe each video into a Transcript.

    A single bad file (no spoken audio, no audio track, unreadable) is skipped
    rather than failing the whole batch; skipped filenames are reported via
    `warnings`. Raises only if *every* video fails.
    """
    transcriber = build_transcriber(settings)
    audio_dir = Path(work_dir) / "audio"
    transcripts: list[Transcript] = []
    skipped: list[str] = []
    n = len(videos)

    for i, video_path in enumerate(videos, start=1):
        session_id = f"S{i}"
        if on_progress:
            on_progress(f"Transcribing session {i} of {n} ({Path(video_path).name})…", (i - 1) / n)
        try:
            if transcriber.name == "mock":
                transcript = transcriber.transcribe(video_path, session_id, video_path)
            else:
                audio_path = extract_audio(video_path, str(audio_dir), settings.ffmpeg_bin)
                transcript = transcriber.transcribe(audio_path, session_id, video_path)
                if not transcript.duration_ms:
                    transcript.duration_ms = probe_duration_ms(video_path, settings.ffprobe_bin)
            transcripts.append(transcript)
        except Exception:  # noqa: BLE001 — one bad file shouldn't sink the batch
            skipped.append(Path(video_path).name)

    if skipped and warnings is not None:
        shown = ", ".join(skipped[:8]) + (" …" if len(skipped) > 8 else "")
        warnings.append(
            f"Skipped {len(skipped)} of {n} video(s) with no usable speech "
            f"(silent, music-only, or no audio track): {shown}"
        )
    if not transcripts:
        raise RuntimeError(
            "None of the videos could be transcribed — they appear to have no spoken "
            "audio. Check that the files contain speech and try again."
        )
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
    on_progress: Optional[ProgressFn] = None,
    warnings: Optional[list] = None,
) -> dict[str, str]:
    """Stage 4: render MP4 + editable timelines. Returns paths by artifact name."""
    settings = settings or load_settings()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress("Writing editable timelines (EDL, FCPXML)…", 0.02)

    report_json = out / "report.json"
    report_json.write_text(json.dumps(report.model_dump(), indent=2))

    edl_path = out / "report.edl"
    edl_path.write_text(timeline.build_edl(report, settings.render_fps))

    fcpxml_path = out / "report.fcpxml"
    fcpxml_path.write_text(timeline.build_fcpxml(report, settings.render_fps))

    # Rendering video is the slow part — it owns the bulk of the progress bar.
    mp4_path = video.render_report(
        report, str(out), settings, on_progress=on_progress, warnings=warnings
    )

    return {
        "mp4": mp4_path,
        "edl": str(edl_path),
        "fcpxml": str(fcpxml_path),
        "report_json": str(report_json),
    }
