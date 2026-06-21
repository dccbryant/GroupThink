"""Finding source videos in a folder."""

from __future__ import annotations

from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm", ".mpg", ".mpeg"}


def list_videos(folder: str, recursive: bool = False) -> list[str]:
    """Video files in `folder`, sorted by path.

    With `recursive`, also descends into subfolders (handy for Drive folders
    that group sessions into subdirectories).
    """
    p = Path(folder).expanduser()
    if not p.is_dir():
        return []
    entries = p.rglob("*") if recursive else p.iterdir()
    return sorted(
        str(f) for f in entries
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS
    )
