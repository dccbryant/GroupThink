"""Command-line entrypoint.

Examples:
    # Full offline demo: synth videos -> transcript -> themes -> MP4 + timelines
    python -m groupthink.cli --demo --out workspace/demo

    # Real footage in a folder, render everything
    python -m groupthink.cli --videos session1.mp4 session2.mp4 --project "Snack Study"

    # Just the reviewable report (no rendering)
    python -m groupthink.cli --videos *.mp4 --project "Snack Study" --no-render
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_settings
from .demo import make_demo_videos
from .pipeline import analyze_sessions, render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="groupthink", description=__doc__)
    parser.add_argument("--videos", nargs="*", default=[], help="Session video files.")
    parser.add_argument("--project", default="Focus Group Study", help="Project name.")
    parser.add_argument("--out", default="workspace/output", help="Output directory.")
    parser.add_argument("--demo", action="store_true", help="Generate synthetic demo videos and run offline.")
    parser.add_argument("--no-render", action="store_true", help="Stop after the reviewable report.")
    args = parser.parse_args(argv)

    settings = load_settings()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    videos = list(args.videos)
    if args.demo:
        print("Generating synthetic demo videos...")
        videos = make_demo_videos(str(out_dir / "sources"), settings)
    if not videos:
        parser.error("Provide --videos or use --demo.")

    print(f"Transcriber: {settings.asr_provider if settings.has_assemblyai else 'mock'}")
    print(f"Analyzer:    {'claude (' + settings.analysis_model + ')' if settings.has_anthropic else 'keyword fallback'}")
    print(f"Analyzing {len(videos)} session(s)...")

    transcripts, report = analyze_sessions(videos, args.project, settings, str(out_dir))

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report.model_dump(), indent=2))
    print(f"\n{len(report.themes)} theme(s) found:")
    for theme in report.themes:
        print(f"  • {theme.title}  ({len(theme.quotes)} quotes)")
    print(f"\nReviewable report written to {report_path}")

    if args.no_render:
        print("Skipping render (--no-render).")
        return 0

    print("\nRendering MP4 + timelines...")
    artifacts = render(report, str(out_dir), settings)
    for name, path in artifacts.items():
        print(f"  {name:12s} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
