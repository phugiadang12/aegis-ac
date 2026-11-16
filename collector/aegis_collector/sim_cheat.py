"""Synthetic *cheater* telemetry — the red team, done the safe way.

We do NOT build a real cheat. Instead we generate the telemetry *signatures*
that each cheat would leave on our own local server, so the blue-team detector
has labelled data to learn from and be scored against. This is how anti-cheat
teams actually develop detectors: you describe the cheat mathematically rather
than run one against a live game.

Every generated player carries a ground-truth ``label`` so detection rate can
be measured precisely. Nothing here reads game memory, injects code, or touches
any real game — it only emits the same telemetry schema the collector ingests.

    python -m aegis_collector.sim_cheat --legit 6 --cheaters 2 --profile aimbot
"""

import argparse
import enum
import math
import random
import socket
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .sim import (
    FIRE_INTERVAL,
    MAP_SIZE,
    MOVE_SPEED,
    WEAPON,
    SimPlayer,
    _bearing,
    _datagrams,
    _wrap180,
)


class Cheat(str, enum.Enum):
    LEGIT = "legit"
    AIMBOT = "aimbot"              # instant snap, perfect accuracy
    HUMANISED = "humanised"        # snap smoothed over a few ticks + jitter
    TRIGGERBOT = "triggerbot"      # inhuman reaction time on the trigger
    ESP = "esp"                    # tracks / pre-aims enemies with no line of sight


# A "line of sight" model. The real game has walls; our flat sim doesn't, so we
# approximate occlusion probabilistically. Legit players only react to a target
# they can see; ESP players react regardless — that difference IS the signal.
def _has_los(rng: random.Random, src, dst) -> bool:
    dist = math.hypot(dst[0] - src[0], dst[1] - src[1])
    # farther apart -> more likely a wall is in the way
    occlusion = min(0.8, dist / MAP_SIZE)
    return rng.random() > occlusion


@dataclass
class CheatPlayer:
    """Wraps the legit SimPlayer model and distorts aim/fire per cheat profile."""

    inner: SimPlayer
    cheat: Cheat
    rng: random.Random
    # humanised-aimbot snap state
    _snap_remaining: int = 0
    _snap_target_yaw: float = 0.0
    # metrics a detector could never see but we use for sanity checks
    shots_at_ghost: int = field(default=0)
    los_violations: int = field(default=0)

    @property
    def cn(self) -> int:
        return self.inner.cn

    def aim_and_fire(
        self,
        t: float,
        dt: float,
        enemies: list["CheatPlayer"],
        ghost_pos: list[float] | None,
        emit,
    ) -> None:
        p = self.inner
        # pick a target using the normal model
        if p.target is None and self.rng.random() < 0.9 * dt:
            alive = [e.inner for e in enemies if e.inner.alive]
            if alive:
                p.target = self.rng.choice(alive)
                p.engaged_for = 0.0
        if p.target is not None and not p.target.alive:
            p.target = None

        # ESP occasionally locks onto a honeypot ghost that legit players can
        # never perceive — a near-certain tell.
        if self.cheat is Cheat.ESP and ghost_pos is not None and self.rng.random() < 0.05:
            self._aim_instant(_bearing(p.pos, ghost_pos))
            self._fire(t, emit)
            self.shots_at_ghost += 1
            return

        if p.target is None:
            return

        desired = _bearing(p.pos, p.target.pos)
        visible = _has_los(self.rng, p.pos, p.target.pos)

        if self.cheat in (Cheat.LEGIT, Cheat.TRIGGERBOT):
            # human aim: limited turn speed, only tracks what it can see
            if not visible:
                return
            p.engaged_for += dt
            speed = p.turn_speed if p.engaged_for > p.reaction else 60.0
            diff = _wrap180(desired - p.yaw)
            turn = max(-speed * dt, min(speed * dt, diff))
            p.yaw = (p.yaw + turn + self.rng.gauss(0, p.aim_noise)) % 360.0
            err = abs(_wrap180(desired - p.yaw))
            if self.cheat is Cheat.TRIGGERBOT:
                # fires the instant the crosshair crosses the enemy: ~0 reaction,
                # and lands the shot far more often than a human on a crossing
                if err < 2.0 and t - p.last_shot >= FIRE_INTERVAL * 0.5:
                    self._fire(t, emit, hit_target=p.target)
            else:
                if err < 6.0 and t - p.last_shot >= FIRE_INTERVAL:
                    hit = p.target if self.rng.random() < p.accuracy else None
                    self._fire(t, emit, hit_target=hit)

        elif self.cheat is Cheat.AIMBOT:
            # instant snap to target every tick -> angular velocity spike
            self._aim_instant(desired)
            if t - p.last_shot >= FIRE_INTERVAL:
                self._fire(t, emit, hit_target=p.target)  # near-perfect accuracy

        elif self.cheat is Cheat.HUMANISED:
            # snap, but spread over 3-5 ticks with jitter to look human-ish
            if self._snap_remaining == 0 and abs(_wrap180(desired - p.yaw)) > 15:
                self._snap_remaining = self.rng.randint(3, 5)
                self._snap_target_yaw = desired
            if self._snap_remaining > 0:
                diff = _wrap180(self._snap_target_yaw - p.yaw)
                p.yaw = (p.yaw + diff / self._snap_remaining + self.rng.gauss(0, 0.6)) % 360.0
                self._snap_remaining -= 1
            else:
                p.yaw = (desired + self.rng.gauss(0, 0.8)) % 360.0
            err = abs(_wrap180(desired - p.yaw))
            if err < 4.0 and t - p.last_shot >= FIRE_INTERVAL:
                hit = p.target if self.rng.random() < 0.85 else None
                self._fire(t, emit, hit_target=hit)

        if self.cheat is Cheat.ESP and not visible and p.target is not None:
            self.los_violations += 1

    def _aim_instant(self, yaw: float) -> None:
        self.inner.yaw = yaw % 360.0

    def _fire(self, t: float, emit, hit_target: SimPlayer | None = None) -> None:
        p = self.inner
        p.last_shot = t
        rad = math.radians(p.yaw)
        far = [p.pos[0] + math.cos(rad) * 60, p.pos[1] + math.sin(rad) * 60, p.pos[2]]
        emit("shot", cn=p.cn, weapon=WEAPON, origin=_vec(p.pos), target=_vec(far))
        if hit_target is not None:
            headshot = self.rng.random() < (0.5 if self.cheat is Cheat.AIMBOT else 0.15)
            amount = self.rng.randint(18, 26) * (2 if headshot else 1)
            hit_target.health -= amount
            emit("damage", attacker=p.cn, target=hit_target.cn, weapon=WEAPON,
                 amount=amount, headshot=headshot)
            if hit_target.health <= 0:
                hit_target.alive = False
                hit_target.respawn_at = t + 3.0
                p.target = None
                emit("kill", attacker=p.cn, victim=hit_target.cn, weapon=WEAPON,
                     headshot=headshot)


def _vec(p: list[float]) -> dict[str, float]:
    return {"x": round(p[0], 3), "y": round(p[1], 3), "z": round(p[2], 3)}


def simulate_mixed(
    n_legit: int = 6,
    n_cheaters: int = 2,
    profile: Cheat = Cheat.AIMBOT,
    seconds: float = 60.0,
    tick_hz: int = 30,
    seed: int | None = None,
    match_id: str | None = None,
    with_ghost: bool = True,
) -> tuple[Iterator[list[dict[str, Any]]], dict[int, str]]:
    """Return (event-tick iterator, ground-truth labels by cn).

    The last ``n_cheaters`` client numbers are cheaters running ``profile``.
    """
    rng = random.Random(seed)
    match_id = match_id or f"mix-{uuid.uuid4().hex[:8]}"
    dt = 1.0 / tick_hz
    total = n_legit + n_cheaters

    players: list[CheatPlayer] = []
    labels: dict[int, str] = {}
    for cn in range(total):
        inner = SimPlayer(cn, f"p{cn:02d}", rng)
        cheat = profile if cn >= n_legit else Cheat.LEGIT
        players.append(CheatPlayer(inner, cheat, rng))
        labels[cn] = cheat.value

    # a honeypot "ghost": a position no real client is told about
    ghost_pos = [MAP_SIZE / 2, MAP_SIZE / 2, 0.0] if with_ghost else None

    def gen() -> Iterator[list[dict[str, Any]]]:
        def base(t: float, kind: str) -> dict[str, Any]:
            return {"ts": round(t * 1000, 1), "match_id": match_id, "type": kind}

        first = []
        for cp in players:
            first.append({**base(0, "player_join"), "cn": cp.cn, "name": cp.inner.name})
            first.append({**base(0, "spawn"), "cn": cp.cn, "pos": _vec(cp.inner.pos)})
        yield first

        t = 0.0
        while t < seconds:
            t += dt
            out: list[dict[str, Any]] = []

            def emit(kind: str, **fields):
                out.append({**base(t, kind), **fields})

            for cp in players:
                p = cp.inner
                if not p.alive:
                    continue
                # movement (shared legit model)
                dx, dy = p.waypoint[0] - p.pos[0], p.waypoint[1] - p.pos[1]
                dist = math.hypot(dx, dy)
                if dist < 2.0:
                    p.waypoint = p._new_waypoint()
                else:
                    step = min(dist, MOVE_SPEED * dt)
                    p.pos[0] += dx / dist * step
                    p.pos[1] += dy / dist * step

                cp.aim_and_fire(t, dt, [o for o in players if o is not cp], ghost_pos, emit)
                emit("tick", cn=p.cn, pos=_vec(p.pos),
                     yaw=round(p.yaw, 3) % 360.0, pitch=round(p.pitch, 3), alive=True)

            for cp in players:
                p = cp.inner
                if not p.alive and t >= getattr(p, "respawn_at", 0):
                    p.respawn()
                    out.append({**base(t, "spawn"), "cn": p.cn, "pos": _vec(p.pos)})
            yield out

        yield [{**base(t, "player_leave"), "cn": cp.cn} for cp in players]

    return gen(), labels


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=28800)
    ap.add_argument("--legit", type=int, default=6)
    ap.add_argument("--cheaters", type=int, default=2)
    ap.add_argument("--profile", type=Cheat, choices=list(Cheat), default=Cheat.AIMBOT)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--tick-hz", type=int, default=30)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--fast", action="store_true")
    args = ap.parse_args()

    ticks, labels = simulate_mixed(
        args.legit, args.cheaters, args.profile, args.seconds, args.tick_hz, args.seed
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sent = 0
    start = time.perf_counter()
    for i, tick in enumerate(ticks):
        for dgram in _datagrams(tick):
            sock.sendto(dgram, (args.host, args.port))
        sent += len(tick)
        if args.fast:
            time.sleep(0.0005)
        else:
            wait = start + i / args.tick_hz - time.perf_counter()
            if wait > 0:
                time.sleep(wait)
    cheat_cns = [cn for cn, l in labels.items() if l != "legit"]
    print(f"sent {sent} events to {args.host}:{args.port}")
    print(f"ground truth: cheaters={cheat_cns} profile={args.profile.value}")


if __name__ == "__main__":
    main()
