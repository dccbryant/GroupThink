from groupthink.models import ms_to_seconds, ms_to_timecode


def test_ms_to_timecode_basic():
    assert ms_to_timecode(0) == "00:00:00:00"
    assert ms_to_timecode(1000, fps=30) == "00:00:01:00"
    assert ms_to_timecode(61_000, fps=30) == "00:01:01:00"
    assert ms_to_timecode(3_600_000, fps=30) == "01:00:00:00"


def test_ms_to_timecode_frames():
    # 500ms at 30fps == 15 frames
    assert ms_to_timecode(500, fps=30) == "00:00:00:15"


def test_ms_to_seconds():
    assert ms_to_seconds(2500) == 2.5
