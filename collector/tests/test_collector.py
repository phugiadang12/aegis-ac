import json
import socket
import time

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aegis_collector.app import create_app
from aegis_collector.schema import EventAdapter
from aegis_collector.sim import _datagrams, simulate

TICK = {"ts": 10, "match_id": "m1", "type": "tick", "cn": 0,
        "pos": {"x": 1, "y": 2, "z": 0}, "yaw": 90, "pitch": 0}
JOIN = {"ts": 0, "match_id": "m1", "type": "player_join", "cn": 0, "name": "alice"}


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- schema ----------

def test_schema_accepts_valid_tick():
    ev = EventAdapter.validate_python(TICK)
    assert ev.type == "tick" and ev.pos.y == 2


@pytest.mark.parametrize("bad", [
    {**TICK, "yaw": 400},                # out of range angle
    {**TICK, "pitch": -91},
    {**TICK, "type": "teleport"},        # unknown event type
    {**TICK, "is_admin": True},          # unexpected field
    {k: v for k, v in TICK.items() if k != "pos"},  # missing field
])
def test_schema_rejects_bad_events(bad):
    with pytest.raises(ValidationError):
        EventAdapter.validate_python(bad)


def test_simulator_only_emits_valid_events():
    n = 0
    for tick in simulate(n_players=6, seconds=20, seed=1):
        for ev in tick:
            EventAdapter.validate_python(ev)
            n += 1
    # 6 players x 30 Hz x 20 s = 3600 tick slots, minus time spent dead
    assert n > 2000


def test_simulator_produces_combat():
    types = [ev["type"] for tick in simulate(n_players=8, seconds=60, seed=2) for ev in tick]
    assert types.count("shot") > 50
    assert types.count("damage") > 10
    assert types.count("kill") > 0


# ---------- HTTP API ----------

@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=tmp_path / "t.db", enable_udp=False)
    with TestClient(app) as c:
        yield c


def test_ingest_and_query(client):
    r = client.post("/ingest", json=[JOIN, TICK])
    assert r.status_code == 200 and r.json() == {"accepted": 2}

    assert client.get("/health").json()["stored"] == 2
    ticks = client.get("/events", params={"type": "tick"}).json()
    assert len(ticks) == 1 and ticks[0]["yaw"] == 90
    assert client.get("/matches/m1/players").json() == [
        {"cn": 0, "name": "alice", "online": True}
    ]


def test_ingest_rejects_invalid_batch(client):
    r = client.post("/ingest", json=[{**TICK, "yaw": -5}])
    assert r.status_code == 422
    assert client.get("/health").json()["stored"] == 0


def test_player_leave_marks_offline(client):
    client.post("/ingest", json=[JOIN, {"ts": 5, "match_id": "m1", "type": "player_leave", "cn": 0}])
    assert client.get("/matches/m1/players").json()[0]["online"] is False


def test_live_websocket_receives_events(client):
    with client.websocket_connect("/ws/live") as ws:
        client.post("/ingest", json=[TICK])
        assert ws.receive_json()["type"] == "tick"


# ---------- UDP path (what the game server uses) ----------

def test_udp_ingest_end_to_end(tmp_path):
    port = _free_udp_port()
    app = create_app(db_path=tmp_path / "u.db", udp_port=port)
    with TestClient(app) as c, socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        good = json.dumps(TICK).encode()
        payload = good + b"\n" + b"{not json}\n" + good + b"\n"
        s.sendto(payload, ("127.0.0.1", port))

        for _ in range(50):
            h = c.get("/health").json()
            if h["accepted"] >= 2:
                break
            time.sleep(0.05)
        assert h["accepted"] == 2
        assert h["rejected"] == 1


def test_datagrams_stay_under_size_limit():
    events = [TICK] * 500
    chunks = list(_datagrams(events, max_bytes=4000))
    assert all(len(c) <= 4000 for c in chunks)
    assert sum(c.count(b"\n") for c in chunks) == 500
