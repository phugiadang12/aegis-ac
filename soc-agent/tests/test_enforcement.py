"""Tests for the delayed ban-wave queue."""

from aegis_soc.enforcement import BanWave, LoggingKickExecutor


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _wave(delay=3600.0):
    clock = FakeClock()
    return BanWave(delay_seconds=delay, clock=clock), clock


def test_enqueue_dedupes_per_match_and_player():
    wave, _ = _wave()
    wave.enqueue("m1", 7, "p07", "esp", 0.95)
    wave.enqueue("m1", 7, "p07", "esp", 0.95)  # same player again
    wave.enqueue("m1", 6, "p06", "esp", 0.95)
    assert len(wave.queued) == 2


def test_queue_is_sorted_by_confidence():
    wave, _ = _wave()
    wave.enqueue("m1", 1, "a", "aimbot", 0.80)
    wave.enqueue("m1", 2, "b", "esp", 0.98)
    assert [r.cn for r in wave.queued] == [2, 1]


def test_release_bans_everyone_and_logs():
    executor = LoggingKickExecutor()
    wave = BanWave(executor=executor, clock=FakeClock())
    wave.enqueue("m1", 7, "p07", "esp", 0.95)
    wave.enqueue("m1", 6, "p06", "esp", 0.90)
    released = wave.release(force=True)
    assert len(released) == 2
    assert all(r.status == "banned" and r.banned_at is not None for r in released)
    assert wave.queued == []
    assert len(wave.history) == 2
    assert wave.wave_count == 1
    assert len(executor.log) == 2


def test_delayed_release_waits_for_the_delay():
    wave, clock = _wave(delay=3600.0)
    wave.enqueue("m1", 7, "p07", "esp", 0.95)
    assert wave.due() is False
    assert wave.release(force=False) == []       # too early
    clock.t += 3600.0                             # delay elapses
    assert wave.due() is True
    assert len(wave.release(force=False)) == 1


def test_seconds_until_due_counts_down():
    wave, clock = _wave(delay=100.0)
    wave.enqueue("m1", 7, "p07", "esp", 0.95)
    assert wave.seconds_until_due == 100.0
    clock.t += 40.0
    assert wave.seconds_until_due == 60.0


def test_empty_wave_releases_nothing():
    wave, _ = _wave()
    assert wave.release(force=True) == []
    assert wave.wave_count == 0
