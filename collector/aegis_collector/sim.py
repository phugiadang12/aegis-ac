"""Simulated *legitimate* players, streamed to the collector over UDP.

Lets us build and test the pipeline (and later the detectors) before the real
AssaultCube server is patched. The aim model is deliberately human-like:
limited turn speed, reaction delay, overshoot noise and imperfect accuracy —
the baseline that cheats will later be compared against.

    python -m aegis_collector.sim --players 8 --seconds 60
"""

import argparse
import json
import math
import random
import socket
import time
import uuid
from collections.abc import Iterator
from typing import Any

MAP_SIZE = 256.0
MOVE_SPEED = 16.0  # units per second
FIRE_INTERVAL = 0.12  # seconds between shots (assault rifle)
WEAPON = "assault"
NAMES = ["viper", "nova", "kestrel", "rook", "ember", "drift", "onyx", "sable",
         "quill", "talon", "brick", "lumen", "moss", "pike", "rune", "wren"]


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _bearing(src: list[float], dst: list[float]) -> float:
    return math.degrees(math.atan2(dst[1] - src[1], dst[0] - src[0])) % 360.0


class SimPlayer:
    def __init__(self, cn: int, name: str, rng: random.Random):
        self.cn = cn
        self.name = name
        self.rng = rng
        # per-player "personality" so players differ from one another
        self.accuracy = rng.uniform(0.25, 0.55)
        self.turn_speed = rng.uniform(180.0, 360.0)  # deg/s when engaging
        self.reaction = max(0.12, rng.gauss(0.26, 0.04))  # seconds
        self.aim_noise = rng.uniform(0.4, 1.2)  # deg of jitter per tick
        self.respawn()

    def respawn(self) -> None:
        r = self.rng
        self.pos = [r.uniform(10, MAP_SIZE - 10), r.uniform(10, MAP_SIZE - 10), 0.0]
        self.yaw = r.uniform(0, 360)
        self.pitch = 0.0
        self.health = 100
        self.alive = True
        self.waypoint = self._new_waypoint()
        self.target: "SimPlayer | None" = None
        self.engaged_for = 0.0
        self.last_shot = -1.0

    def _new_waypoint(self) -> list[float]:
        r = self.rng
        return [r.uniform(10, MAP_SIZE - 10), r.uniform(10, MAP_SIZE - 10), 0.0]


def simulate(
    n_players: int = 8,
    seconds: float = 60.0,
    tick_hz: int = 30,
    seed: int | None = None,
    match_id: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the events for each tick, as JSON-ready dicts."""
    rng = random.Random(seed)
    match_id = match_id or f"sim-{uuid.uuid4().hex[:8]}"
    dt = 1.0 / tick_hz
    players = [SimPlayer(cn, NAMES[cn % len(NAMES)], rng) for cn in range(n_players)]

    def base(t: float, kind: str) -> dict[str, Any]:
        return {"ts": round(t * 1000, 1), "match_id": match_id, "type": kind}

    def vec(p: list[float]) -> dict[str, float]:
        return {"x": round(p[0], 3), "y": round(p[1], 3), "z": round(p[2], 3)}

    first = []
    for p in players:
        first.append({**base(0, "player_join"), "cn": p.cn, "name": p.name})
        first.append({**base(0, "spawn"), "cn": p.cn, "pos": vec(p.pos)})
    yield first

    t = 0.0
    while t < seconds:
        t += dt
        out: list[dict[str, Any]] = []
        for p in players:
            if not p.alive:
                continue

            # --- choose / drop a target ---
            if p.target is None and rng.random() < 0.7 * dt:
                enemies = [e for e in players if e is not p and e.alive]
                if enemies:
                    p.target, p.engaged_for = rng.choice(enemies), 0.0
            if p.target is not None and (not p.target.alive or rng.random() < 0.25 * dt):
                p.target = None

            # --- movement ---
            dx, dy = p.waypoint[0] - p.pos[0], p.waypoint[1] - p.pos[1]
            dist = math.hypot(dx, dy)
            if dist < 2.0:
                p.waypoint = p._new_waypoint()
            else:
                step = min(dist, MOVE_SPEED * dt)
                p.pos[0] += dx / dist * step
                p.pos[1] += dy / dist * step

            # --- aim: humans turn at a limited speed, with a reaction delay ---
            if p.target is not None:
                p.engaged_for += dt
                desired = _bearing(p.pos, p.target.pos)
                speed = p.turn_speed if p.engaged_for > p.reaction else 60.0
            else:
                desired = _bearing(p.pos, p.waypoint)
                speed = 120.0
            diff = _wrap180(desired - p.yaw)
            turn = max(-speed * dt, min(speed * dt, diff))
            p.yaw = (p.yaw + turn + rng.gauss(0, p.aim_noise)) % 360.0
            p.pitch = max(-90.0, min(90.0, p.pitch * 0.8 + rng.gauss(0, 0.5)))

            out.append({**base(t, "tick"), "cn": p.cn, "pos": vec(p.pos),
                        "yaw": round(p.yaw, 3) % 360.0, "pitch": round(p.pitch, 3),
                        "alive": True})

            # --- shooting ---
            err = abs(_wrap180(desired - p.yaw)) if p.target else 999.0
            if p.target is not None and err < 6.0 and t - p.last_shot >= FIRE_INTERVAL:
                p.last_shot = t
                rad = math.radians(p.yaw)
                far = [p.pos[0] + math.cos(rad) * 60, p.pos[1] + math.sin(rad) * 60, p.pos[2]]
                out.append({**base(t, "shot"), "cn": p.cn, "weapon": WEAPON,
                            "origin": vec(p.pos), "target": vec(far)})

                if rng.random() < p.accuracy * (1 - err / 10):
                    victim = p.target
                    headshot = rng.random() < 0.12
                    amount = rng.randint(18, 26) * (2 if headshot else 1)
                    victim.health -= amount
                    out.append({**base(t, "damage"), "attacker": p.cn, "target": victim.cn,
                                "weapon": WEAPON, "amount": amount, "headshot": headshot})
                    if victim.health <= 0:
                        victim.alive = False
                        victim.respawn_at = t + 3.0
                        p.target = None
                        out.append({**base(t, "kill"), "attacker": p.cn, "victim": victim.cn,
                                    "weapon": WEAPON, "headshot": headshot})

        for p in players:
            if not p.alive and t >= getattr(p, "respawn_at", 0):
                p.respawn()
                out.append({**base(t, "spawn"), "cn": p.cn, "pos": vec(p.pos)})

        yield out

    yield [{**base(t, "player_leave"), "cn": p.cn} for p in players]


def _datagrams(events: list[dict[str, Any]], max_bytes: int = 8000) -> Iterator[bytes]:
    """Pack events as JSON lines into datagrams below a safe UDP size."""
    buf = b""
    for ev in events:
        line = json.dumps(ev, separators=(",", ":")).encode() + b"\n"
        if buf and len(buf) + len(line) > max_bytes:
            yield buf
            buf = b""
        buf += line
    if buf:
        yield buf


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=28800)
    ap.add_argument("--players", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--tick-hz", type=int, default=30)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--fast", action="store_true", help="don't wait in real time")
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    start = time.perf_counter()
    for i, tick in enumerate(simulate(args.players, args.seconds, args.tick_hz, args.seed)):
        for dgram in _datagrams(tick):
            sock.sendto(dgram, (args.host, args.port))
        sent += len(tick)
        if args.fast:
            time.sleep(0.0005)  # tiny pause so the local UDP buffer doesn't overflow
        else:
            wait = start + i / args.tick_hz - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
    print(f"sent {sent} events to {args.host}:{args.port}")


if __name__ == "__main__":
    main()
