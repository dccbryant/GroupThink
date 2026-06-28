from pathlib import Path

import pytest

from groupthink import runtime
from groupthink.config import load_settings


def test_resource_path_resolves_a_real_file():
    """The bundled DejaVuSans font is reachable via resource_path in source mode."""
    p = runtime.resource_path("groupthink", "assets", "DejaVuSans.ttf")
    assert p.exists(), f"Expected bundled font at {p}"


def test_is_frozen_is_false_when_running_from_source():
    assert runtime.is_frozen() is False
    assert runtime.bundle_root() is None


def test_find_binary_env_override(monkeypatch, tmp_path: Path):
    fake = tmp_path / "ffmpeg-stub"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("FFMPEG_BIN", str(fake))
    assert runtime.find_binary("ffmpeg") == str(fake)


def test_find_binary_falls_through_to_name_when_nothing_found(monkeypatch):
    """Without any binary on PATH or env, falls through to the bare name."""
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent/never/here")
    monkeypatch.setattr(runtime, "shutil", _StubShutil())
    monkeypatch.setattr(runtime.Path, "exists", lambda self: False)
    assert runtime.find_binary("ffmpeg") == "ffmpeg"


class _StubShutil:
    def which(self, _name):  # pragma: no cover — trivial stub
        return None


def test_settings_load_with_bundle_resolvers():
    """load_settings() still works once config uses the runtime helpers."""
    s = load_settings()
    assert s.ffmpeg_bin  # never empty
    assert s.ffprobe_bin
    assert s.work_dir
    assert s.analysis_model == "claude-opus-4-8"


@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe"])
def test_find_binary_returns_a_string(name):
    assert isinstance(runtime.find_binary(name), str)
