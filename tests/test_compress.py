from pathlib import Path

from groupthink.compress import human_size, list_videos


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2 * 1024) == "2.0 KB"
    assert human_size(3 * 1024 * 1024) == "3.0 MB"
    assert human_size(4 * 1024 * 1024 * 1024) == "4.0 GB"


def test_list_videos_filters_and_sorts(tmp_path: Path):
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "a.mov").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("nope")
    (tmp_path / "sub").mkdir()  # directories are ignored
    found = list_videos(str(tmp_path))
    assert [Path(p).name for p in found] == ["a.mov", "b.mp4"]


def test_list_videos_missing_folder():
    assert list_videos("/no/such/folder/here") == []
