"""Feature extraction: raw telemetry events -> one feature row per player.

Everything here is computable from the exact telemetry the collector already
stores, so a detector trained on these features can run against real matches,
not just the simulator. Each feature targets a known cheat tell:

    max_turn_rate   deg/s, peak single-tick view change  -> aimbot snap
    p95_turn_rate   deg/s, sustained fast turning         -> humanised aimbot
    hit_rate        damage dealt per shot                 -> aimbot / triggerbot
    headshot_rate   headshots per hit                     -> aim assistance
    honeypot_shots  shots aimed at the server's phantom   -> ESP / wallhack
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# A view change slower than this between two ticks separated by a bigger gap is
# almost certainly a respawn teleport, not a turn — skip those pairs.
MAX_TICK_GAP_S = 0.1
# A shot whose direction lands within this of the (hidden) honeypot phantom is
# treated as fired AT the phantom — but only when no *real* enemy is within the
# same angle of the aim, so a legit player shooting an enemy who merely happens
# to be near the phantom's bearing is never counted.
HONEYPOT_ANGLE_DEG = 6.0


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


@dataclass
class PlayerFeatures:
    cn: int
    name: str = ""
    ticks: int = 0
    shots: int = 0
    hits: int = 0
    kills: int = 0
    deaths: int = 0
    headshots: int = 0
    max_turn_rate: float = 0.0
    p95_turn_rate: float = 0.0
    honeypot_shots: int = 0
    _turn_rates: list[float] = field(default_factory=list, repr=False)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.shots if self.shots else 0.0

    @property
    def headshot_rate(self) -> float:
        return self.headshots / self.hits if self.hits else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cn": self.cn, "name": self.name, "ticks": self.ticks,
            "shots": self.shots, "hits": self.hits, "kills": self.kills,
            "deaths": self.deaths,
            "hit_rate": round(self.hit_rate, 3),
            "headshot_rate": round(self.headshot_rate, 3),
            "max_turn_rate": round(self.max_turn_rate, 1),
            "p95_turn_rate": round(self.p95_turn_rate, 1),
            "honeypot_shots": self.honeypot_shots,
        }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100 * (len(s) - 1)))))
    return s[k]


def extract_features(events: list[dict[str, Any]]) -> dict[int, PlayerFeatures]:
    """Build a feature row per player from one match's events."""
    feats: dict[int, PlayerFeatures] = {}

    def row(cn: int) -> PlayerFeatures:
        if cn not in feats:
            feats[cn] = PlayerFeatures(cn=cn)
        return feats[cn]

    last_tick: dict[int, tuple[float, float]] = {}        # cn -> (ts_ms, yaw)
    honeypot: dict[float, tuple[float, float]] = {}       # ts_ms -> (x, y)
    positions: dict[float, dict[int, tuple[float, float]]] = defaultdict(dict)

    for ev in events:
        t = ev["type"]
        if t == "player_join":
            row(ev["cn"]).name = ev["name"]
        elif t == "tick":
            r = row(ev["cn"])
            r.ticks += 1
            positions[ev["ts"]][ev["cn"]] = (ev["pos"]["x"], ev["pos"]["y"])
            prev = last_tick.get(ev["cn"])
            if prev is not None:
                dt = (ev["ts"] - prev[0]) / 1000.0
                if 0 < dt <= MAX_TICK_GAP_S:
                    rate = abs(_wrap180(ev["yaw"] - prev[1])) / dt
                    r._turn_rates.append(rate)
                    r.max_turn_rate = max(r.max_turn_rate, rate)
            last_tick[ev["cn"]] = (ev["ts"], ev["yaw"])
        elif t == "shot":
            row(ev["cn"]).shots += 1
        elif t == "damage":
            r = row(ev["attacker"])
            r.hits += 1
            if ev.get("headshot"):
                r.headshots += 1
        elif t == "kill":
            row(ev["attacker"]).kills += 1
            row(ev["victim"]).deaths += 1
        elif t == "honeypot":
            honeypot[ev["ts"]] = (ev["pos"]["x"], ev["pos"]["y"])

    for r in feats.values():
        r.p95_turn_rate = _percentile(r._turn_rates, 95)

    _score_honeypot(events, honeypot, positions, feats)
    return feats


def _score_honeypot(events, honeypot, positions, feats) -> None:
    """Count shots a player aimed at the phantom entity. Legit clients are never
    told it exists, so aiming at it — a moving target, tracked per tick — is a
    near-certain wallhack/ESP tell. A shot only counts when the phantom is on
    the aim line AND no real enemy is, so shooting an enemy who merely happens
    to share the phantom's bearing is not mistaken for a wallhack."""
    if not honeypot:
        return
    for ev in events:
        if ev["type"] != "shot":
            continue
        ghost = honeypot.get(ev["ts"])
        if ghost is None:
            continue
        shooter = ev["cn"]
        ox, oy = ev["origin"]["x"], ev["origin"]["y"]
        aim = math.degrees(math.atan2(ev["target"]["y"] - oy, ev["target"]["x"] - ox))
        to_ghost = math.degrees(math.atan2(ghost[1] - oy, ghost[0] - ox))
        if abs(_wrap180(aim - to_ghost)) > HONEYPOT_ANGLE_DEG:
            continue
        # is a real enemy also on this aim line? then it's a normal shot
        enemy_near = any(
            abs(_wrap180(math.degrees(math.atan2(py - oy, px - ox)) - aim))
            <= HONEYPOT_ANGLE_DEG
            for cn, (px, py) in positions.get(ev["ts"], {}).items()
            if cn != shooter
        )
        if not enemy_near:
            feats[shooter].honeypot_shots += 1
