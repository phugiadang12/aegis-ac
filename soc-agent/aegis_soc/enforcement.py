"""Delayed ban waves.

Anti-cheat teams rarely ban the moment they detect a cheat. If a cheater is
kicked instantly, the cheat author knows exactly which build/feature tripped the
detector and patches it. Instead, confirmed cheaters are collected and banned in
a *wave* at a later time, so detections can't be correlated to a specific match
or cheat version. This module models that queue.

The actual "kick" is pluggable: ``LoggingKickExecutor`` just records the action
(what the demo uses), and a real deployment would drop in an executor that
issues the AssaultCube server's admin/disconnect command.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class BanRecord:
    match_id: str
    cn: int
    name: str
    category: str
    confidence: float
    queued_at: float
    status: str = "queued"          # queued -> banned
    banned_at: float | None = None

    def as_dict(self) -> dict:
        return {
            "match_id": self.match_id, "cn": self.cn, "name": self.name,
            "category": self.category, "confidence": round(self.confidence, 2),
            "queued_at": self.queued_at, "status": self.status,
            "banned_at": self.banned_at,
        }


class KickExecutor(Protocol):
    def kick(self, record: BanRecord) -> str: ...


class LoggingKickExecutor:
    """Records the enforcement action instead of touching a real server."""

    def __init__(self) -> None:
        self.log: list[str] = []

    def kick(self, record: BanRecord) -> str:
        line = (f"BAN  {record.name} (cn {record.cn}) from match "
                f"{record.match_id} — {record.category} "
                f"@ {record.confidence*100:.0f}% confidence")
        self.log.append(line)
        return line


class BanWave:
    """A queue of confirmed cheaters released together on command (or once the
    delay elapses). One player per match is enqueued at most once."""

    def __init__(self, executor: KickExecutor | None = None,
                 delay_seconds: float = 3600.0, clock=time.time) -> None:
        self.executor = executor or LoggingKickExecutor()
        self.delay_seconds = delay_seconds
        self._clock = clock
        self._queue: dict[tuple[str, int], BanRecord] = {}
        self.history: list[BanRecord] = []
        self.wave_count = 0

    def enqueue(self, match_id: str, cn: int, name: str,
                category: str, confidence: float) -> BanRecord:
        key = (match_id, cn)
        rec = self._queue.get(key)
        if rec is None:
            rec = BanRecord(match_id, cn, name, category, confidence,
                            queued_at=self._clock())
            self._queue[key] = rec
        return rec

    @property
    def queued(self) -> list[BanRecord]:
        return sorted(self._queue.values(), key=lambda r: r.confidence, reverse=True)

    @property
    def seconds_until_due(self) -> float:
        if not self._queue:
            return 0.0
        oldest = min(r.queued_at for r in self._queue.values())
        return max(0.0, self.delay_seconds - (self._clock() - oldest))

    def due(self) -> bool:
        return bool(self._queue) and self.seconds_until_due <= 0.0

    def release(self, force: bool = True) -> list[BanRecord]:
        """Ban everyone currently queued. ``force=False`` only releases once the
        delay has elapsed (how a scheduler would call it)."""
        if not self._queue or (not force and not self.due()):
            return []
        released = self.queued
        now = self._clock()
        for rec in released:
            rec.status = "banned"
            rec.banned_at = now
            self.executor.kick(rec)
        self.history.extend(released)
        self._queue.clear()
        self.wave_count += 1
        return released

    def snapshot(self) -> dict:
        return {
            "queued": [r.as_dict() for r in self.queued],
            "history": [r.as_dict() for r in self.history],
            "waves_released": self.wave_count,
            "delay_seconds": self.delay_seconds,
            "seconds_until_due": round(self.seconds_until_due, 1),
            "enforcement_log": getattr(self.executor, "log", []),
        }
