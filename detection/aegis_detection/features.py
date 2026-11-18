"""Feature extraction: raw telemetry events -> one feature row per player.

Everything here is computed from the telemetry the game server already sends
(ticks with position + view angles, shots with origin -> target, damage, kills),
so it runs on real AssaultCube matches, not only on the simulator. Each feature
targets a known cheat tell:

    max_turn_rate       deg/s, peak single-tick view change       -> aimbot snap
    p95_turn_rate       deg/s, sustained fast turning              -> humanised aimbot
    fight_p95_turn_rate deg/s, p95 only in the second before shots -> aimbot in fights
    hit_rate            damage events per shot                     -> aimbot / triggerbot
    headshot_rate       headshots per hit                          -> aim assistance
    honeypot_shots      shots aimed at the server's phantom        -> ESP / wallhack
    lock_error_median   deg between crosshair and enemy at a shot  -> aimbot lock-on
    reaction_median_ms  crosshair-on-enemy -> first shot           -> triggerbot
    off_view_hits       hits whose shot left far from the view     -> silent aim
    shot_offset_median  deg between view and shot direction        -> silent aim

Lessons from the real game are built in:
  * A respawn teleports the player and resets the view. Without care it looks
    like a 900+ deg/s snap (it caused a false flag in the first live lab), so
    turn pairs with a position jump are skipped.
  * Real shots leave a few degrees off the view (spread + recoil), so silent-aim
    checks use a generous margin, measured from real matches.
"""

import bisect
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

# A view change between two ticks separated by a bigger gap is not a turn.
MAX_TICK_GAP_S = 0.1
# Normal movement in real AssaultCube is < 1 unit per tick (p99.9 = 0.8).
# A bigger jump between two ticks is a respawn / teleport: skip that turn pair.
TELEPORT_UNITS = 8.0
# Honeypot: a shot within this angle of the phantom, with no real enemy on the line.
HONEYPOT_ANGLE_DEG = 6.0
# Crosshair counts as "on an enemy" within this angle (yaw/pitch distance).
ON_TARGET_DEG = 4.0
# Lock-on precision is only measured on shots with an enemy this close to the crosshair.
LOCK_WINDOW_DEG = 20.0
# Real shots leave up to ~7 deg (yaw) / ~14 deg (pitch, recoil) from the view in our
# lab data. A hit whose shot left further away than this was not aimed with the view.
SILENT_OFFSET_DEG = 25.0
# A damage event this soon after a shot belongs to that shot.
HIT_LINK_MS = 80.0
# Reaction: only count when the player had not fired for this long (not a spray).
REACTION_QUIET_MS = 300.0
# A reaction this fast is one server tick or less: faster than any human.
INSTANT_REACTION_MS = 60.0
# Fight window for fight_p95_turn_rate.
FIGHT_WINDOW_MS = 1000.0


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round(pct / 100 * (len(s) - 1)))))
    return s[k]


def detect_convention(events: list[dict[str, Any]]) -> str:
    """Real AssaultCube matches (match_id ``ac-...``) use the game's own yaw
    convention; the simulator uses the maths convention (0 deg = +x)."""
    for ev in events:
        mid = str(ev.get("match_id", ""))
        if mid:
            return "ac" if mid.startswith("ac-") else "sim"
    return "sim"


def aim_angles(src: dict, dst: dict, convention: str) -> tuple[float, float]:
    """(yaw, pitch) a player at ``src`` must look at to aim at ``dst``."""
    dx, dy = dst["x"] - src["x"], dst["y"] - src["y"]
    dz = dst.get("z", 0.0) - src.get("z", 0.0)
    if convention == "ac":
        yaw = (-math.degrees(math.atan2(dx, dy)) + 180.0) % 360.0   # AssaultCube
    else:
        yaw = math.degrees(math.atan2(dy, dx)) % 360.0
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return yaw, pitch


def angle_between(yaw1: float, pitch1: float, yaw2: float, pitch2: float) -> float:
    return math.hypot(_wrap180(yaw1 - yaw2), pitch1 - pitch2)


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
    fight_p95_turn_rate: float = 0.0
    honeypot_shots: int = 0
    teleports: int = 0
    lock_samples: int = 0
    lock_error_median: float = 0.0
    reaction_samples: int = 0
    reaction_median_ms: float = 0.0
    instant_reactions: int = 0
    shot_offset_median: float = 0.0
    off_view_hits: int = 0
    _turn_rates: list[tuple[float, float]] = field(default_factory=list, repr=False)
    _shot_ts: list[float] = field(default_factory=list, repr=False)
    _lock_errors: list[float] = field(default_factory=list, repr=False)
    _reactions: list[float] = field(default_factory=list, repr=False)
    _shot_offsets: list[float] = field(default_factory=list, repr=False)

    @property
    def hit_rate(self) -> float:
        return self.hits / self.shots if self.shots else 0.0

    @property
    def headshot_rate(self) -> float:
        return self.headshots / self.hits if self.hits else 0.0

    @property
    def instant_reaction_rate(self) -> float:
        return self.instant_reactions / self.reaction_samples if self.reaction_samples else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "cn": self.cn, "name": self.name, "ticks": self.ticks,
            "shots": self.shots, "hits": self.hits, "kills": self.kills,
            "deaths": self.deaths,
            "hit_rate": round(self.hit_rate, 3),
            "headshot_rate": round(self.headshot_rate, 3),
            "max_turn_rate": round(self.max_turn_rate, 1),
            "p95_turn_rate": round(self.p95_turn_rate, 1),
            "fight_p95_turn_rate": round(self.fight_p95_turn_rate, 1),
            "honeypot_shots": self.honeypot_shots,
            "teleports_skipped": self.teleports,
            "lock_samples": self.lock_samples,
            "lock_error_median": round(self.lock_error_median, 2),
            "reaction_samples": self.reaction_samples,
            "reaction_median_ms": round(self.reaction_median_ms, 1),
            "instant_reaction_rate": round(self.instant_reaction_rate, 3),
            "shot_offset_median": round(self.shot_offset_median, 2),
            "off_view_hits": self.off_view_hits,
        }


def extract_features(events: list[dict[str, Any]]) -> dict[int, PlayerFeatures]:
    """Build a feature row per player from one match's events (in time order)."""
    conv = detect_convention(events)
    feats: dict[int, PlayerFeatures] = {}

    def row(cn: int) -> PlayerFeatures:
        if cn not in feats:
            feats[cn] = PlayerFeatures(cn=cn)
        return feats[cn]

    last_tick: dict[int, dict] = {}                        # cn -> latest tick event
    on_target_since: dict[int, float | None] = {}          # cn -> ts crosshair landed on an enemy
    reaction_open: dict[int, bool] = {}                    # cn -> waiting for first shot
    last_shot: dict[int, tuple[float, float]] = {}         # cn -> (ts, offset deg)
    honeypot: dict[float, tuple[float, float]] = {}
    positions: dict[float, dict[int, tuple[float, float]]] = defaultdict(dict)

    def nearest_enemy_error(cn: int, view: dict) -> float:
        best = math.inf
        for other, t in last_tick.items():
            if other == cn or not t.get("alive", True):
                continue
            y, p = aim_angles(view["pos"], t["pos"], conv)
            best = min(best, angle_between(y, p, view["yaw"], view.get("pitch", 0.0)))
        return best

    for ev in events:
        t = ev["type"]
        if t == "player_join":
            row(ev["cn"]).name = ev["name"]
        elif t == "tick":
            cn = ev["cn"]
            r = row(cn)
            r.ticks += 1
            positions[ev["ts"]][cn] = (ev["pos"]["x"], ev["pos"]["y"])
            prev = last_tick.get(cn)
            if prev is not None and ev.get("alive", True) and prev.get("alive", True):
                dt = (ev["ts"] - prev["ts"]) / 1000.0
                jump = math.dist(
                    (ev["pos"]["x"], ev["pos"]["y"], ev["pos"].get("z", 0.0)),
                    (prev["pos"]["x"], prev["pos"]["y"], prev["pos"].get("z", 0.0)))
                if jump > TELEPORT_UNITS:
                    r.teleports += 1                      # respawn: not a turn
                elif 0 < dt <= MAX_TICK_GAP_S:
                    rate = abs(_wrap180(ev["yaw"] - prev["yaw"])) / dt
                    r._turn_rates.append((ev["ts"], rate))
                    r.max_turn_rate = max(r.max_turn_rate, rate)
            last_tick[cn] = ev

            # reaction tracking: when does the crosshair land on an enemy?
            on = nearest_enemy_error(cn, ev) <= ON_TARGET_DEG
            if on and on_target_since.get(cn) is None:
                quiet = ev["ts"] - last_shot.get(cn, (-1e12, 0))[0] >= REACTION_QUIET_MS
                on_target_since[cn] = ev["ts"]
                reaction_open[cn] = quiet
            elif not on:
                on_target_since[cn] = None
                reaction_open[cn] = False
        elif t == "shot":
            cn = ev["cn"]
            r = row(cn)
            r.shots += 1
            r._shot_ts.append(ev["ts"])
            view = last_tick.get(cn)
            offset = 0.0
            if view is not None:
                sy, sp = aim_angles(ev["origin"], ev["target"], conv)
                offset = angle_between(sy, sp, view["yaw"], view.get("pitch", 0.0))
                r._shot_offsets.append(offset)
                err = nearest_enemy_error(cn, view)
                if err <= LOCK_WINDOW_DEG:
                    r._lock_errors.append(err)
            since = on_target_since.get(cn)
            if since is not None and reaction_open.get(cn):
                r._reactions.append(max(0.0, ev["ts"] - since))
                reaction_open[cn] = False
            last_shot[cn] = (ev["ts"], offset)
        elif t == "damage":
            r = row(ev["attacker"])
            r.hits += 1
            if ev.get("headshot"):
                r.headshots += 1
            shot = last_shot.get(ev["attacker"])
            if shot and ev["ts"] - shot[0] <= HIT_LINK_MS and shot[1] > SILENT_OFFSET_DEG:
                r.off_view_hits += 1
        elif t == "kill":
            row(ev["attacker"]).kills += 1
            row(ev["victim"]).deaths += 1
        elif t == "honeypot":
            honeypot[ev["ts"]] = (ev["pos"]["x"], ev["pos"]["y"])

    for r in feats.values():
        rates = [rate for _, rate in r._turn_rates]
        r.p95_turn_rate = _percentile(rates, 95)
        if r._shot_ts:
            shots = sorted(r._shot_ts)
            fight = [rate for ts, rate in r._turn_rates
                     if (i := bisect.bisect_left(shots, ts)) < len(shots)
                     and shots[i] - ts <= FIGHT_WINDOW_MS]
            r.fight_p95_turn_rate = _percentile(fight, 95)
        r.lock_samples = len(r._lock_errors)
        r.lock_error_median = _median(r._lock_errors)
        r.reaction_samples = len(r._reactions)
        r.reaction_median_ms = _median(r._reactions)
        r.instant_reactions = sum(1 for x in r._reactions if x <= INSTANT_REACTION_MS)
        r.shot_offset_median = _median(r._shot_offsets)

    _score_honeypot(events, honeypot, positions, feats)
    return feats


def _score_honeypot(events, honeypot, positions, feats) -> None:
    """Count shots a player aimed at the phantom entity. Legit clients are never
    told it exists, so aiming at it is a near-certain wallhack/ESP tell. A shot
    only counts when the phantom is on the aim line AND no real enemy is."""
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
        enemy_near = any(
            abs(_wrap180(math.degrees(math.atan2(py - oy, px - ox)) - aim))
            <= HONEYPOT_ANGLE_DEG
            for cn, (px, py) in positions.get(ev["ts"], {}).items()
            if cn != shooter
        )
        if not enemy_near:
            feats[shooter].honeypot_shots += 1
