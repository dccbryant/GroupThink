"""FastAPI web app: upload sessions, review the themes, then render.

The flow mirrors the recommended pipeline: analysis is fast and produces a
reviewable report; the researcher edits/approves it in the browser; rendering
(the slow, expensive step) only happens on demand.

Run with:  uvicorn groupthink.web.app:app --reload
"""

from __future__ import annotations

import dataclasses
import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from ..config import Settings, load_settings
from ..demo import make_demo_videos
from ..models import ThemeReport
from ..pipeline import analyze_sessions, render

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


def _run_analysis(project_id: str, project_name: str, videos: list[str]) -> ThemeReport:
    out_dir = _project_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    _transcripts, report = analyze_sessions(videos, project_name, current_settings(), str(out_dir))
    _PROJECTS[project_id] = {"name": project_name, "videos": videos}
    _save_report(project_id, report)
    return report


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


@app.post("/api/projects")
async def create_project(
    project: str = Form("Focus Group Study"),
    files: Optional[List[UploadFile]] = None,  # noqa: UP006,UP007 — runtime-evaluated by FastAPI; keep 3.9-safe
) -> dict:
    """Upload session videos and run analysis. Returns the reviewable report."""
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

    report = _run_analysis(project_id, project, video_paths)
    return {"project_id": project_id, "report": report.model_dump()}


@app.post("/api/demo")
def create_demo() -> dict:
    """One-click demo: synthesize session videos and run the full analysis."""
    project_id = uuid.uuid4().hex[:12]
    sources_dir = _project_dir(project_id) / "sources"
    videos = make_demo_videos(str(sources_dir), current_settings())
    report = _run_analysis(project_id, "Demo Focus Group", videos)
    return {"project_id": project_id, "report": report.model_dump()}


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


@app.post("/api/projects/{project_id}/render")
def render_project(project_id: str) -> dict:
    """Render the (possibly edited) report into MP4 + timelines."""
    report = _load_report(project_id)
    out_dir = _project_dir(project_id) / "output"
    artifacts = render(report, str(out_dir), current_settings())
    return {
        "artifacts": {
            name: f"/api/projects/{project_id}/download/{name}"
            for name in artifacts
        }
    }


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
