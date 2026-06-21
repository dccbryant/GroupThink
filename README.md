# GroupThink

Turn raw focus-group footage into a presentable, themed highlight reel —
automatically.

Researchers normally watch every session, identify the themes that recur across
them, and hand-cut a video where each theme opens with a title card followed by a
few supporting respondent quotes. GroupThink automates that workflow end to end.

## How it works

```
Raw session videos
   │
   ▼
1. EXTRACT AUDIO      ffmpeg pulls the audio track from each video
   │
   ▼
2. TRANSCRIBE + DIARIZE  speech-to-text with word-level timecodes and
   │                      speaker labels (who said what, when)
   ▼
3. FIND THEMES        Claude reads every transcript, finds the themes that
   │                   recur ACROSS sessions, and picks 3-6 supporting quotes
   ▼                   per theme — each referenced by utterance id, so timecodes
   │                   are resolved from the transcript, never hallucinated
4. REVIEW             a human approves/edits the themes and quotes (web UI)
   │
   ▼
5. ASSEMBLE           ffmpeg opens with the video's title card, then per theme a
   │                   title card + its quote clips (white sans-serif on black,
   ▼                   flush-left, fading), and renders:
                        • a rough-cut MP4
                        • an editable timeline (EDL + FCPXML) for Premiere /
                          DaVinci Resolve / Final Cut
```

### Where Claude fits

The theme-finding and quote-selection step (3) is the researcher's judgment —
exactly what Claude is good at, and the heart of the tool. It runs on
`claude-opus-4-8` with structured output (Pydantic) so the result is always a
valid, typed report, and prompt caching on the transcript so re-runs are cheap.

Claude does **not** transcribe audio (that needs a speech-to-text service with
**speaker diarization** — AssemblyAI here) and does **not** render video (ffmpeg
does). GroupThink is the pipeline that wires these together with Claude as the
analytical brain.

## Quick start (no API keys required)

GroupThink ships an **offline mode**: a mock transcriber and a keyword-based
analyzer let you run the entire pipeline — including a real MP4 render — with no
keys and no network.

Requires Python 3.9+ and `ffmpeg` on your PATH.

```bash
pip install -r requirements.txt          # ffmpeg must also be on PATH

# One-shot CLI demo: synth videos → transcript → themes → MP4 + timelines
python -m groupthink.cli --demo --out workspace/demo

# Or the web app
uvicorn groupthink.web.app:app --reload
# open http://localhost:8000 and click "Try the demo"
```

## Large footage (many big videos)

Research sessions are often 20 files of several GB each. Two features keep that
manageable:

**Shrink the videos first.** Focus-group footage is talking heads, so a 720p
proxy looks fine in the reel and is typically 5–10× smaller:

```bash
python -m groupthink.compress --in ~/sessions --out ~/sessions_small
# options: --height 720  --crf 28   (lower crf = better quality, bigger files)
```

**Analyze a folder in place — no upload, no second copy.** In the web app, paste
a **folder path** instead of choosing files; GroupThink reads the videos where
they already live (uploads copy each file into the project, doubling disk use).
Combine the two: compress to a folder, then point the app at that folder.

## Production use

Set keys (see `.env.example`) to switch on the real backends:

| Variable             | Enables                                                |
| -------------------- | ----------------------------------------------------- |
| `ANTHROPIC_API_KEY`  | Claude theme analysis (instead of keyword fallback)   |
| `ASSEMBLYAI_API_KEY` | Diarized transcription (instead of the mock)          |

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export ASSEMBLYAI_API_KEY=...
uvicorn groupthink.web.app:app
```

The web app shows live badges for which backends are active.

### CLI

```bash
# Real footage, full render
python -m groupthink.cli --videos s1.mp4 s2.mp4 s3.mp4 --project "Snack Study"

# Just the reviewable report, no render
python -m groupthink.cli --videos *.mp4 --project "Snack Study" --no-render
```

## Outputs

For each project GroupThink produces:

- **`highlight_reel.mp4`** — rough cut: title card per theme, then the quote clips.
- **`report.edl`** / **`report.fcpxml`** — editable timelines to refine the cut in
  an NLE instead of re-finding every clip by hand.
- **`report.json`** — the structured themes → quotes → timecodes, for review or
  feeding into other tools.
- **Word document** — "Save to Word doc" in the review step exports the themes,
  summaries, and quotes (with speaker, source, and timecode) as a `.docx` for
  sharing. (Falls back to an HTML `.doc` if `python-docx` isn't installed.)

The MP4 is the fastest watchable result; the timelines are the better handoff for
a polished edit. Rendering is the slow, expensive step, so it only happens after a
report is approved.

## Layout

```
groupthink/
  audio.py             stage 1 — ffmpeg audio extraction
  transcription/       stage 2 — diarized transcription (AssemblyAI / mock)
  analysis.py          stage 3 — Claude theme + quote selection (Pydantic + caching)
  assembly/
    video.py           stage 4a — ffmpeg render to MP4
    timeline.py        stage 4b — EDL + FCPXML export
  pipeline.py          orchestrates the stages
  web/                 FastAPI app + single-page review UI
  cli.py               command-line entrypoint
  demo.py              synthetic videos for the offline demo
tests/                 pure-Python unit tests (run: python -m pytest)
```

## Tests

```bash
python -m pytest
```

## Notes & limitations

- The MP4 is a **rough cut** (no music, lower-thirds, or transitions) — use the
  timeline exports for a finished edit.
- Diarization labels speakers as "Speaker A/B/…"; mapping those to named
  respondents is a natural next step.
- Analysis and rendering run as background jobs with a live progress bar; errors
  (e.g. a bad API key) surface in the UI instead of as a generic 500. Jobs are
  tracked in memory, so they don't survive a server restart.
