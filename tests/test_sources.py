from pathlib import Path

from groupthink.sources import list_videos


def test_lists_top_level_videos_only_by_default(tmp_path: Path):
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "a.mov").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("nope")
    sub = tmp_path / "session3"
    sub.mkdir()
    (sub / "c.mp4").write_bytes(b"x")

    found = list_videos(str(tmp_path))
    assert [Path(p).name for p in found] == ["a.mov", "b.mp4"]  # subfolder excluded


def test_recursive_includes_subfolders(tmp_path: Path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    sub = tmp_path / "session3"
    sub.mkdir()
    (sub / "c.mp4").write_bytes(b"x")
    (sub / "ignore.txt").write_text("nope")

    found = [Path(p).name for p in list_videos(str(tmp_path), recursive=True)]
    assert found == ["a.mp4", "c.mp4"]


def test_missing_folder_returns_empty():
    assert list_videos("/no/such/folder/here") == []
