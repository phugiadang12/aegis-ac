"""SQLite event store. Raw events are kept as JSON so detectors can replay them."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .schema import Event, actor_of

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT    NOT NULL,
    ts       REAL    NOT NULL,
    type     TEXT    NOT NULL,
    actor    INTEGER,
    payload  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_match_ts ON events(match_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_match_actor ON events(match_id, actor);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
"""


class EventStore:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs sync endpoints in worker threads, so share one
        # connection behind a lock rather than one per thread.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)

    def add_many(self, events: list[Event]) -> None:
        rows = [
            (e.match_id, e.ts, e.type, actor_of(e), e.model_dump_json())
            for e in events
        ]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO events (match_id, ts, type, actor, payload) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def recent(
        self,
        limit: int = 100,
        type: str | None = None,
        match_id: str | None = None,
        actor: int | None = None,
    ) -> list[dict[str, Any]]:
        """Newest events first."""
        where, args = [], []
        for column, value in (("type", type), ("match_id", match_id), ("actor", actor)):
            if value is not None:
                where.append(f"{column} = ?")
                args.append(value)
        sql = "SELECT payload FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [json.loads(r[0]) for r in rows]

    def matches(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT match_id, COUNT(*), MIN(ts), MAX(ts) FROM events "
                "GROUP BY match_id ORDER BY MIN(id) DESC"
            ).fetchall()
        return [
            {"match_id": m, "events": n, "first_ts": a, "last_ts": b}
            for m, n, a, b in rows
        ]

    def players(self, match_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM events WHERE match_id = ? "
                "AND type IN ('player_join', 'player_leave') ORDER BY id",
                (match_id,),
            ).fetchall()
        players: dict[int, dict[str, Any]] = {}
        for (payload,) in rows:
            ev = json.loads(payload)
            if ev["type"] == "player_join":
                players[ev["cn"]] = {"cn": ev["cn"], "name": ev["name"], "online": True}
            elif ev["cn"] in players:
                players[ev["cn"]]["online"] = False
        return sorted(players.values(), key=lambda p: p["cn"])

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
