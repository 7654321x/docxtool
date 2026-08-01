import pytest

from docxtool.web.maintenance import cleaner_loop


def test_cleaner_loop_sleeps_at_least_one_minute_and_does_not_cleanup():
    calls = []

    def stop_after_sleep(seconds: float) -> None:
        calls.append(seconds)
        raise RuntimeError("stop loop")

    with pytest.raises(RuntimeError, match="stop loop"):
        cleaner_loop(0, sleep=stop_after_sleep)

    assert calls == [60]


def test_cleaner_loop_converts_minutes_to_seconds():
    calls = []

    def stop_after_sleep(seconds: float) -> None:
        calls.append(seconds)
        raise RuntimeError("stop loop")

    with pytest.raises(RuntimeError, match="stop loop"):
        cleaner_loop(3, sleep=stop_after_sleep)

    assert calls == [180]
