"""Bundle-aware path and binary resolution.

GroupThink runs in two shapes:
- a source checkout (``pip install -r requirements.txt`` + ``uvicorn``)
- a frozen macOS desktop app (PyInstaller-built ``GroupThink.app``)

The helpers here let the rest of the codebase stay shape-agnostic: data files
load the same way from either form, and ffmpeg/ffprobe are found bundled-first
in the .app and PATH-first from source.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path | None:
    """The PyInstaller ``_MEIPASS`` dir, or ``None`` when running from source."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else None


def resource_path(*parts: str) -> Path:
    """Locate a packaged data file (works in source and bundle).

    Falls back to the source tree's root when not frozen — handy for tests.
    """
    root = bundle_root() or Path(__file__).resolve().parent.parent
    return root.joinpath(*parts)


def app_support_dir() -> Path:
    """Per-user, writable directory for projects, workspace, and the like.

    macOS: ``~/Library/Application Support/GroupThink``
    Other: ``~/.groupthink``
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GroupThink"
    return Path.home() / ".groupthink"


def find_binary(name: str) -> str:
    """Locate an external binary (ffmpeg, ffprobe).

    Resolution order:
    1. Bundled in the PyInstaller .app at ``vendor/bin/<name>``
    2. ``<NAME>_BIN`` environment override (e.g. ``FFMPEG_BIN``)
    3. On ``PATH`` (``shutil.which``)
    4. Common macOS install locations (Homebrew)

    Falls through to the bare name if nothing matches — ``subprocess`` will
    then raise ``FileNotFoundError``, which the caller surfaces to the user.
    """
    root = bundle_root()
    if root is not None:
        candidate = root / "vendor" / "bin" / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

    env_override = os.getenv(f"{name.upper()}_BIN")
    if env_override and Path(env_override).exists():
        return env_override

    on_path = shutil.which(name)
    if on_path:
        return on_path

    for fallback in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if Path(fallback).exists():
            return fallback

    return name
