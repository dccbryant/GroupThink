"""FastAPI web app: upload sessions, review the themes, then render.

The flow mirrors the recommended pipeline: analysis is fast and produces a
reviewable report; the researcher edits/approves it in the browser; rendering
(the slow, expensive step) only happens on demand.

Run with:  uvicorn groupthink.web.app:app --reload
"""

from __future__ import annotations

import dataclasses
import json
import os
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
from ..models import AnalysisBrief
from ..runtime import is_frozen
from ..sources import list_videos
from ..demo import make_demo_videos
from ..models import ThemeReport
from ..pipeline import render, transcribe_sessions

app = FastAPI(title="GroupThink")
SETTINGS = load_settings()
PROJECTS_ROOT = Path(SETTINGS.work_dir) / "projects"
PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

# In-memory index of projects -> their source video paths. Reports live on disk.
_PROJECTS: dict[str, dict] = {}

# Keys pasted into the UI live here. They override the environment, and are
# persisted to a user-only file so they survive restarts (see below). They are
# never echoed back to the client.
_RUNTIME_KEYS: dict[str, Optional[str]] = {"anthropic": None, "assemblyai": None}

# Persist keys to the user's home so they don't need re-pasting each restart.
_KEYS_FILE = Path.home() / ".groupthink" / "keys.json"


def _load_persisted_keys() -> None:
    try:
        data = json.loads(_KEYS_FILE.read_text())
    except (OSError, ValueError):
        return
    for name in ("anthropic", "assemblyai"):
        value = data.get(name)
        if value:
            _RUNTIME_KEYS[name] = value


def _persist_keys() -> None:
    """Write current keys to a user-only (0600) file."""
    try:
        _KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEYS_FILE.write_text(json.dumps({k: v for k, v in _RUNTIME_KEYS.items() if v}))
        os.chmod(_KEYS_FILE, 0o600)
        os.chmod(_KEYS_FILE.parent, 0o700)
    except OSError:
        pass


_load_persisted_keys()

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


class JobCancelled(Exception):
    """Raised inside a worker when the user has cancelled the job."""


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "status": "running",   # running | done | error | cancelled
            "step": "Starting…",
            "progress": 0.0,
            "error": None,
            "result": None,
            "cancel_requested": False,
        }
    return job_id


def _update_job(job_id: str, **fields) -> None:
    with _JOBS_LOCK:
        _JOBS[job_id].update(fields)


def _is_cancelled(job_id: str) -> bool:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _progress(job_id: str, base: float, span: float) -> Callable[[str, float], None]:
    """A pipeline progress callback that maps a 0-1 fraction into [base, base+span].

    Doubles as a cooperative-cancel checkpoint: if the user has hit Cancel,
    the next progress tick raises JobCancelled so the worker can exit cleanly.
    """
    def cb(message: str, frac: float) -> None:
        if _is_cancelled(job_id):
            raise JobCancelled()
        _update_job(job_id, step=message, progress=round(base + span * frac, 3))
    return cb


def _spawn(job_id: str, target: Callable[[], None]) -> None:
    def runner() -> None:
        try:
            target()
        except JobCancelled:
            _update_job(job_id, status="cancelled", step="Cancelled.", error=None)
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


def _clean_folder_path(raw: str) -> str:
    """Normalize a pasted folder path.

    macOS "Copy as Pathname" (and dragging into Terminal) can wrap the path in
    quotes or backslash-escape spaces — strip those so users don't have to.
    """
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1]
    s = s.replace("\\ ", " ")  # un-escape shell-style spaces
    return s.strip()


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
    brief: AnalysisBrief | None = None,
    make_demo: bool = False,
) -> None:
    """Run transcription + theme analysis, reporting progress into the job."""
    settings = current_settings()
    out_dir = _project_dir(project_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if make_demo:
        _update_job(job_id, step="Generating demo footage…", progress=0.05)
        videos = make_demo_videos(str(out_dir / "sources"), settings)

    warnings: list[str] = []
    # Transcription is the slow part for real footage -> give it 5%..70%.
    transcripts = transcribe_sessions(
        videos, settings, str(out_dir),
        on_progress=_progress(job_id, 0.05, 0.65), warnings=warnings,
    )

    using = "Claude" if settings.has_anthropic else "keyword fallback"
    _update_job(job_id, step=f"Finding themes across sessions ({using})…", progress=0.72)
    if _is_cancelled(job_id):
        raise JobCancelled()
    analysis = build_analyzer(settings).analyze(transcripts, project_name, brief)
    # The Claude call can't be interrupted mid-flight, but if the user pressed
    # Cancel while it was running we should drop the result rather than persist it.
    if _is_cancelled(job_id):
        raise JobCancelled()

    _update_job(job_id, step="Resolving quotes and timecodes…", progress=0.94)
    report = resolve_report(analysis, transcripts, project_name)
    report.title = title.strip() or None  # on-screen opening-card title

    _PROJECTS[project_id] = {"name": project_name, "videos": videos}
    _save_report(project_id, report)
    result: dict = {"project_id": project_id, "report": report.model_dump()}
    if warnings:
        result["warning"] = " ".join(warnings)
    _update_job(job_id, status="done", step="Analysis complete.", progress=1.0, result=result)


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
        "keys_saved": _KEYS_FILE.exists(),
        # True when running as the bundled macOS .app. The UI uses this to
        # switch download links to "save to Downloads" buttons, since pywebview
        # navigates the window on a download link instead of saving a file.
        "desktop": is_frozen(),
    }


class KeyUpdate(BaseModel):
    anthropic_api_key: Optional[str] = None
    assemblyai_api_key: Optional[str] = None


@app.post("/api/settings")
def update_keys(update: KeyUpdate) -> dict:
    """Store pasted API keys and persist them for next time.

    A blank field is ignored (so it won't wipe a key already set). Keys are
    written to a user-only file in your home directory and never returned to the
    client.
    """
    if update.anthropic_api_key and update.anthropic_api_key.strip():
        _RUNTIME_KEYS["anthropic"] = update.anthropic_api_key.strip()
    if update.assemblyai_api_key and update.assemblyai_api_key.strip():
        _RUNTIME_KEYS["assemblyai"] = update.assemblyai_api_key.strip()
    _persist_keys()
    return status()


@app.post("/api/settings/forget")
def forget_keys() -> dict:
    """Clear saved keys (reverts to environment variables, if any)."""
    _RUNTIME_KEYS["anthropic"] = None
    _RUNTIME_KEYS["assemblyai"] = None
    try:
        _KEYS_FILE.unlink(missing_ok=True)
    except OSError:
        pass
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


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Ask a running job to stop. Honored at the next progress checkpoint."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Unknown job.")
        if job["status"] == "running":
            job["cancel_requested"] = True
    return {"ok": True}


@app.post("/api/projects")
async def create_project(
    project: str = Form("Focus Group Study"),
    title: str = Form(""),
    folder: str = Form(""),
    recursive: str = Form(""),
    topics: str = Form(""),
    restrict_topics: str = Form(""),
    discussion_guide: str = Form(""),
    files: Optional[List[UploadFile]] = None,  # noqa: UP006,UP007 — runtime-evaluated by FastAPI; keep 3.9-safe
) -> dict:
    """Start analysis from uploaded files OR a local folder path.

    Folder mode reads the videos in place (no upload, no second copy on disk) —
    the better choice for large footage. With `recursive`, subfolders are
    searched too. Returns a job id to poll.
    """
    project_id = uuid.uuid4().hex[:12]
    video_paths: list[str] = []

    if files:
        # Upload mode: copy each file into the project's sources directory.
        sources_dir = _project_dir(project_id) / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        for upload in files:
            dest = sources_dir / Path(upload.filename or "session.mp4").name
            with dest.open("wb") as fh:
                shutil.copyfileobj(upload.file, fh)
            video_paths.append(str(dest))
    elif folder.strip():
        # Local-folder mode: use the videos where they already live.
        folder_path = Path(_clean_folder_path(folder)).expanduser()
        if not folder_path.is_dir():
            raise HTTPException(400, f"Folder not found on this computer: {folder_path}")
        recurse = recursive.strip().lower() in ("1", "true", "on", "yes")
        video_paths = list_videos(str(folder_path), recursive=recurse)
        if not video_paths:
            where = "folder or its subfolders" if recurse else "folder"
            raise HTTPException(400, f"No video files found in that {where}: {folder_path}")
    else:
        raise HTTPException(400, "Choose videos to upload, or paste a folder path.")

    brief = AnalysisBrief(
        topics=topics,
        restrict_to_topics=restrict_topics.strip().lower() in ("1", "true", "on", "yes"),
        discussion_guide=discussion_guide,
    )
    job_id = _new_job()
    _spawn(job_id, lambda: _analyze_job(job_id, project_id, project, video_paths, title=title, brief=brief))
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
    warnings: list[str] = []
    artifacts = render(
        report, str(out_dir), current_settings(),
        on_progress=_progress(job_id, 0.0, 1.0), warnings=warnings,
    )
    result: dict = {
        "artifacts": {
            name: f"/api/projects/{project_id}/download/{name}" for name in artifacts
        }
    }
    if warnings:
        result["warning"] = " ".join(warnings)
    _update_job(job_id, status="done", step="Render complete.", progress=1.0, result=result)


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


# --------------------------------------------------------------------------- #
# Save-to-Downloads (desktop .app)
#
# pywebview navigates the window to a download URL rather than triggering a
# browser-style save dialog. The desktop UI uses this endpoint to write the
# artifact straight to ~/Downloads/, leaving the app exactly where it was.
# --------------------------------------------------------------------------- #


def _unique_destination(directory: Path, filename: str) -> Path:
    """Pick a path under `directory` that doesn't clobber an existing file."""
    dest = directory / filename
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    for n in range(2, 1000):
        candidate = directory / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Couldn't find a free filename in Downloads.")


def _safe_filename(name: str, default: str) -> str:
    cleaned = "".join(c for c in (name or "") if c.isalnum() or c in " -_().").strip()
    return cleaned or default


@app.post("/api/projects/{project_id}/save/{artifact}")
def save_artifact(project_id: str, artifact: str) -> dict:
    """Copy an artifact (or the generated Word doc) to ~/Downloads/."""
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    report = _load_report(project_id)  # 404 if no report yet
    project_name = _safe_filename(report.project, "GroupThink")

    if artifact == "document":
        try:
            data = build_docx(report)
            filename = f"{project_name}.docx"
        except ImportError:
            data = build_doc_html(report).encode("utf-8")
            filename = f"{project_name}.doc"
        dest = _unique_destination(downloads, filename)
        dest.write_bytes(data)
        return {"saved": str(dest), "filename": dest.name}

    spec = _ARTIFACT_FILES.get(artifact)
    if spec is None:
        raise HTTPException(404, "Unknown artifact.")
    rel, _media = spec
    src = _project_dir(project_id) / rel
    if not src.exists():
        raise HTTPException(404, "Artifact not rendered yet.")
    # Rename the saved copy to something more human than the internal name.
    nice_names = {
        "mp4": f"{project_name} — highlight reel.mp4",
        "edl": f"{project_name}.edl",
        "fcpxml": f"{project_name}.fcpxml",
        "report_json": f"{project_name} report.json",
    }
    dest = _unique_destination(downloads, nice_names.get(artifact, src.name))
    shutil.copy2(src, dest)
    return {"saved": str(dest), "filename": dest.name}
