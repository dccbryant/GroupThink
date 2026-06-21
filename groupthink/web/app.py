"""FastAPI web app: upload sessions, review the themes, then render.

The flow mirrors the recommended pipeline: analysis is fast and produces a
reviewable report; the researcher edits/approves it in the browser; rendering
(the slow, expensive step) only happens on demand.

Run with:  uvicorn groupthink.web.app:app --reload
"""

from __future__ import annotations

import dataclasses
import shutil
import threading
import uuid
from pathlib import Path
from typing import Callable, List, Optional

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from ..analysis import build_analyzer, resolve_report
from ..assembly.document import build_doc_html, build_docx
from ..config import Settings, load_settings
from ..demo import make_demo_videos
from ..models import ThemeReport
from ..pipeline import render, transcribe_sessions

app = FastAPI(title="GroupThink")
SETTINGS = load_settings()
PROJECTS_ROOT = Path(SETTINGS.work_dir) / "projects"
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

# In-memory index of projects -> their source video paths. Reports live on disk.
_PROJECTS: dict[str, dict] = {}

# Keys pasted into the UI live here, in memory only, for this server process.
# They override the environment but are never written to disk or echoed back.
_RUNTIME_KEYS: dict[str, Optional[str]] = {"anthropic": None, "assemblyai": None}

_STATIC = Path(__file__).parent / "static"


# --------------------------------------------------------------------------- #
# Background jobs
#
# Analysis and rendering can take a while (real transcription, a Claude call,
# ffmpeg). Running them inside the HTTP request gives the browser no feedback
# and risks proxy/timeout 500s, so each runs in a background thread that reports
# progress the page can poll.
# --------------------------------------------------------------------------- #

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",   # running | done | error
            "step": "Starting…",
            "progress": 0.0,
            "error": None,
            "result": None,
        }
    return job_id


def _update_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id].update(fields)


def _progress(job_id: str, base: float, span: float) -> Callable[[str, float], None]:
    """A pipeline progress callback that maps a 0-1 fraction into [base, base+span]."""
    def cb(message: str, frac: float) -> None:
        _update_job(job_id, step=message, progress=round(base + span * frac, 3))
    return cb


def _spawn(job_id: str, target: Callable[[], None]) -> None:
    def runner() -> None:
        try:
            target()
        except Exception as exc:  # surface the real reason instead of a blank 500
            _update_job(job_id, status="error", error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=runner, daemon=True).start()


def current_settings() -> Settings:
    """Settings from the environment, with any UI-pasted keys layered on top."""
    base = load_settings()
    return dataclasses.replace(
        base,
        anthropic_api_key=_RUNTIME_KEYS["anthropic"] or base.anthropic_api_key,
        assemblyai_api_key=_RUNTIME_KEYS["assemblyai"] or base.assemblyai_api_key,
    )


def _project_dir(project_id: str) -> Path:
    return PROJECTS_ROOT / project_id


def _load_report(project_id: str) -> ThemeReport:
    path = _project_dir(project_id) / "report.json"
    if not path.exists():
        raise HTTPException(404, "Project or report not found.")
    return ThemeReport.model_validate_json(path.read_text())


def _save_report(project_id: str, report: ThemeReport) -> None:
    (_project_dir(project_id) / "report.json").write_text(
        report.model_dump_json(indent=2)
    )


def _analyze_job(
    job_id: str,
    project_id: str,
    project_name: str,
    videos: list[str],
    title: str = "",
    make_demo: bool = False,
) -> None:
    """Run transcription + theme analysis, reporting progress into the job."""
    settings = current_settings()
    out_dir = _project_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if make_demo:
        _update_job(job_id, step="Generating demo footage…", progress=0.05)
        videos = make_demo_videos(str(out_dir / "sources"), settings)

    # Transcription is the slow part for real footage -> give it 5%..70%.
    transcripts = transcribe_sessions(
        videos, settings, str(out_dir), on_progress=_progress(job_id, 0.05, 0.65)
    )

    using = "Claude" if settings.has_anthropic else "keyword fallback"
    _update_job(job_id, step=f"Finding themes across sessions ({using})…", progress=0.72)
    analysis = build_analyzer(settings).analyze(transcripts, project_name)

    _update_job(job_id, step="Resolving quotes and timecodes…", progress=0.94)
    report = resolve_report(analysis, transcripts, project_name)
    report.title = title.strip() or None  # on-screen opening-card title

    _PROJECTS[project_id] = {"name": project_name, "videos": videos}
    _save_report(project_id, report)
    _update_job(
        job_id,
        status="done",
        step="Analysis complete.",
        progress=1.0,
        result={"project_id": project_id, "report": report.model_dump()},
    )


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (_STATIC / "index.html").read_text()


@app.get("/api/status")
def status() -> dict:
    s = current_settings()
    return {
        "transcriber": s.asr_provider if s.has_assemblyai else "mock",
        "diarization": s.has_assemblyai,
        "analyzer": s.analysis_model if s.has_anthropic else "keyword-fallback",
        "claude": s.has_anthropic,
        # True when the key came from the environment (so the UI can show it's
        # already set without ever revealing the value).
        "anthropic_from_env": bool(load_settings().anthropic_api_key),
        "assemblyai_from_env": bool(load_settings().assemblyai_api_key),
    }


class KeyUpdate(BaseModel):
    anthropic_api_key: Optional[str] = None
    assemblyai_api_key: Optional[str] = None


@app.post("/api/settings")
def update_keys(update: KeyUpdate) -> dict:
    """Store pasted API keys in memory for this server process.

    A blank field is ignored (so it won't wipe a key already set via the
    environment). Keys are never persisted to disk or returned to the client.
    """
    if update.anthropic_api_key and update.anthropic_api_key.strip():
        _RUNTIME_KEYS["anthropic"] = update.anthropic_api_key.strip()
    if update.assemblyai_api_key and update.assemblyai_api_key.strip():
        _RUNTIME_KEYS["assemblyai"] = update.assemblyai_api_key.strip()
    return status()


# --------------------------------------------------------------------------- #
# Project lifecycle
# --------------------------------------------------------------------------- #


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """Poll a background job's progress, result, or error."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        return dict(job)


@app.post("/api/projects")
async def create_project(
    project: str = Form("Focus Group Study"),
    title: str = Form(""),
    files: Optional[List[UploadFile]] = None,  # noqa: UP006,UP007 — runtime-evaluated by FastAPI; keep 3.9-safe
) -> dict:
    """Upload session videos and kick off analysis. Returns a job id to poll."""
    if not files:
        raise HTTPException(400, "Upload at least one session video.")

    project_id = uuid.uuid4().hex[:12]
    sources_dir = _project_dir(project_id) / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    video_paths: list[str] = []
    for upload in files:
        dest = sources_dir / Path(upload.filename or "session.mp4").name
        with dest.open("wb") as fh:
            shutil.copyfileobj(upload.file, fh)
        video_paths.append(str(dest))

    job_id = _new_job()
    _spawn(job_id, lambda: _analyze_job(job_id, project_id, project, video_paths, title=title))
    return {"job_id": job_id, "project_id": project_id}


@app.post("/api/demo")
def create_demo() -> dict:
    """One-click demo: synthesize session videos and run the full analysis."""
    project_id = uuid.uuid4().hex[:12]
    job_id = _new_job()
    _spawn(job_id, lambda: _analyze_job(job_id, project_id, "Demo Focus Group", [], make_demo=True))
    return {"job_id": job_id, "project_id": project_id}


@app.get("/api/projects/{project_id}/report")
def get_report(project_id: str) -> dict:
    return _load_report(project_id).model_dump()


@app.put("/api/projects/{project_id}/report")
def update_report(project_id: str, report: ThemeReport) -> dict:
    """Persist researcher edits to the report before rendering."""
    if not _project_dir(project_id).exists():
        raise HTTPException(404, "Project not found.")
    _save_report(project_id, report)
    return {"ok": True}


@app.get("/api/projects/{project_id}/document")
def document(project_id: str) -> Response:
    """Download the themes + quotes as a Word document (.docx, or .doc fallback)."""
    report = _load_report(project_id)
    safe = "".join(c for c in report.project if c.isalnum() or c in " -_").strip() or "report"
    try:
        data = build_docx(report)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{safe}.docx"'},
        )
    except ImportError:
        # python-docx isn't installed — hand back an HTML doc Word opens cleanly.
        return Response(
            content=build_doc_html(report),
            media_type="application/msword",
            headers={"Content-Disposition": f'attachment; filename="{safe}.doc"'},
        )


def _render_job(job_id: str, project_id: str) -> None:
    report = _load_report(project_id)
    out_dir = _project_dir(project_id) / "output"
    artifacts = render(
        report, str(out_dir), current_settings(), on_progress=_progress(job_id, 0.0, 1.0)
    )
    _update_job(
        job_id,
        status="done",
        step="Render complete.",
        progress=1.0,
        result={
            "artifacts": {
                name: f"/api/projects/{project_id}/download/{name}" for name in artifacts
            }
        },
    )


@app.post("/api/projects/{project_id}/render")
def render_project(project_id: str) -> dict:
    """Kick off rendering the (possibly edited) report. Returns a job id to poll."""
    _load_report(project_id)  # 404 early if the project/report is missing
    job_id = _new_job()
    _spawn(job_id, lambda: _render_job(job_id, project_id))
    return {"job_id": job_id}


_ARTIFACT_FILES = {
    "mp4": ("output/highlight_reel.mp4", "video/mp4"),
    "edl": ("output/report.edl", "text/plain"),
    "fcpxml": ("output/report.fcpxml", "application/xml"),
    "report_json": ("output/report.json", "application/json"),
}


@app.get("/api/projects/{project_id}/download/{artifact}")
def download(project_id: str, artifact: str):
    spec = _ARTIFACT_FILES.get(artifact)
    if spec is None:
        raise HTTPException(404, "Unknown artifact.")
    rel, media_type = spec
    path = _project_dir(project_id) / rel
    if not path.exists():
        raise HTTPException(404, "Artifact not rendered yet.")
    return FileResponse(str(path), media_type=media_type, filename=path.name)
