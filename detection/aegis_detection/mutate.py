"""Telemetry mutation: test the detector against cheats we don't have yet.

A server never sees a cheat, only the telemetry it leaves behind. So instead of
building cheats, we take a REAL recorded match and change only the part of the
telemetry a given cheat would have to change. Everything else (movement, aim
noise, timing, the other players) stays real.

Mutations (each has a strength "level"):

    silent_aim    hits leave LEVEL degrees away from where the player looked
                  (the view stays put, the bullet goes elsewhere)
    triggerbot    in LEVEL (0-1) of engagements, a shot fires on the same tick
                  the crosshair reaches the enemy
    smooth_lock   at each shot the crosshair is pulled LEVEL (0-1) of the way
                  onto the nearest enemy, like a smoothed aimbot

Then the normal detector + assessment runs on the mutated match, so we can see
at which strength each cheat gets caught, and whether it gets the right label.

    # sweep every mutation over a range of strengths, on one player
    python -m aegis_detection.mutate --db data/lab.db --match ac-1794961039-2 --sweep

    # write one mutated copy into the database, for scan / aegis_soc / dashboard
    python -m aegis_detection.mutate --db data/lab.db --match ac-1794961039-2 \\
        --kind silent_aim --level 30 --save

Mutated matches are saved as ``<match_id>-mut-<kind>-<level>`` and never touch
the original events.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import random
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

from .classify import assess
from .features import (
    HIT_LINK_MS,
    LOCK_WINDOW_DEG,
    ON_TARGET_DEG,
    REACTION_QUIET_MS,
    aim_angles,
    angle_between,
    detect_convention,
    extract_features,
)
from .rules import judge

Event = dict[str, Any]

# default strength sweeps
LEVELS = {
    "silent_aim": [0, 5, 10, 15, 20, 25, 30, 45, 60],
    "triggerbot": [0, 0.1, 0.25, 0.5, 0.75, 1.0],
    "smooth_lock": [0, 0.25, 0.5, 0.75, 0.9, 1.0],
}
# the cheat type the assessment should name for each mutation
EXPECTED_TYPE = {"silent_aim": "silent_aim", "triggerbot": "triggerbot", "smooth_lock": "aimbot"}
UNITS = {"silent_aim": "deg", "triggerbot": "share", "smooth_lock": "pull"}


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _point(src: dict, yaw: float, pitch: float, dist: float, convention: str) -> dict:
    """The point ``dist`` away from ``src`` along (yaw, pitch); inverse of aim_angles."""
    y, p = math.radians(yaw), math.radians(pitch)
    flat = math.cos(p) * dist
    if convention == "ac":
        dx, dy = math.sin(y) * flat, -math.cos(y) * flat
    else:
        dx, dy = math.cos(y) * flat, math.sin(y) * flat
    return {"x": round(src["x"] + dx, 3), "y": round(src["y"] + dy, 3),
            "z": round(src.get("z", 0.0) + math.sin(p) * dist, 3)}


def _sorted(events: list[Event]) -> list[Event]:
    return sorted(events, key=lambda e: e.get("ts", 0))


def _shots_with_view(events: list[Event], cn: int):
    """Yield (index, shot, view_tick, other_ticks) for each shot by ``cn``."""
    last: dict[int, Event] = {}
    for i, ev in enumerate(events):
        if ev["type"] == "tick":
            last[ev["cn"]] = ev
        elif ev["type"] == "shot" and ev["cn"] == cn and cn in last:
            yield i, ev, last[cn], {k: v for k, v in last.items() if k != cn}


def _hit_shots(events: list[Event], cn: int) -> set[int]:
    """Indices of shots by ``cn`` that are followed by a damage event from ``cn``."""
    hits, pending = set(), None
    for i, ev in enumerate(events):
        if ev["type"] == "shot" and ev["cn"] == cn:
            pending = (i, ev["ts"])
        elif ev["type"] == "damage" and ev["attacker"] == cn and pending:
            if ev["ts"] - pending[1] <= HIT_LINK_MS:
                hits.add(pending[0])
            pending = None
    return hits


# --- mutations ----------------------------------------------------------------
def silent_aim(events: list[Event], cn: int, offset_deg: float, seed: int = 0) -> list[Event]:
    """Every hit by ``cn`` leaves ``offset_deg`` away from the view direction."""
    if offset_deg <= 0:
        return copy.deepcopy(events)
    rng, conv = random.Random(seed), detect_convention(events)
    out = copy.deepcopy(_sorted(events))
    hits = _hit_shots(out, cn)
    for i, shot, view, _ in list(_shots_with_view(out, cn)):
        if i not in hits:
            continue
        o, t = shot["origin"], shot["target"]
        dist = math.dist((o["x"], o["y"], o.get("z", 0)), (t["x"], t["y"], t.get("z", 0))) or 50.0
        yaw = view["yaw"] + rng.choice((-1, 1)) * offset_deg
        shot["target"] = _point(o, yaw % 360.0, view.get("pitch", 0.0), dist, conv)
    return out


def triggerbot(events: list[Event], cn: int, share: float, seed: int = 0) -> list[Event]:
    """In ``share`` of engagements, fire (and hit) on the tick the crosshair
    reaches an enemy. Engagements are found exactly as the detector finds them."""
    if share <= 0:
        return copy.deepcopy(events)
    rng, conv = random.Random(seed), detect_convention(events)
    base = copy.deepcopy(_sorted(events))
    last: dict[int, Event] = {}
    on_since: Event | None = None
    last_shot_ts = -1e12
    inserts: list[Event] = []
    for ev in base:
        if ev["type"] == "shot" and ev["cn"] == cn:
            last_shot_ts = ev["ts"]
        if ev["type"] != "tick":
            continue
        last[ev["cn"]] = ev
        if ev["cn"] != cn:
            continue
        best, target = math.inf, None
        for other, t in last.items():
            if other == cn or not t.get("alive", True):
                continue
            y, p = aim_angles(ev["pos"], t["pos"], conv)
            err = angle_between(y, p, ev["yaw"], ev.get("pitch", 0.0))
            if err < best:
                best, target = err, other
        if best <= ON_TARGET_DEG:
            if on_since is None:
                on_since = ev
                quiet = ev["ts"] - last_shot_ts >= REACTION_QUIET_MS
                if quiet and rng.random() < share:
                    ts = ev["ts"] + 5
                    inserts.append({"ts": ts, "match_id": ev["match_id"], "type": "shot",
                                    "cn": cn, "weapon": "g6", "origin": dict(ev["pos"]),
                                    "target": _point(ev["pos"], ev["yaw"], ev.get("pitch", 0.0), 50.0, conv)})
                    inserts.append({"ts": ts + 3, "match_id": ev["match_id"], "type": "damage",
                                    "attacker": cn, "target": target, "weapon": "g6",
                                    "amount": 20, "headshot": False})
                    last_shot_ts = ts
        else:
            on_since = None
    return _sorted(base + inserts)


def smooth_lock(events: list[Event], cn: int, pull: float, seed: int = 0) -> list[Event]:
    """At each shot with an enemy near the crosshair, pull the view ``pull`` of the
    way onto that enemy (the shot keeps its normal spread around the view)."""
    if pull <= 0:
        return copy.deepcopy(events)
    conv = detect_convention(events)
    out = copy.deepcopy(_sorted(events))
    for _, shot, view, others in list(_shots_with_view(out, cn)):
        best, aim = math.inf, None
        for t in others.values():
            if not t.get("alive", True):
                continue
            y, p = aim_angles(view["pos"], t["pos"], conv)
            err = angle_between(y, p, view["yaw"], view.get("pitch", 0.0))
            if err < best:
                best, aim = err, (y, p)
        if aim is None or best > LOCK_WINDOW_DEG:
            continue
        o, tg = shot["origin"], shot["target"]
        sy, sp = aim_angles(o, tg, conv)
        spread_y, spread_p = _wrap180(sy - view["yaw"]), sp - view.get("pitch", 0.0)
        view["yaw"] = (view["yaw"] + _wrap180(aim[0] - view["yaw"]) * pull) % 360.0
        view["pitch"] = view.get("pitch", 0.0) + (aim[1] - view.get("pitch", 0.0)) * pull
        dist = math.dist((o["x"], o["y"], o.get("z", 0)), (tg["x"], tg["y"], tg.get("z", 0))) or 50.0
        shot["target"] = _point(o, (view["yaw"] + spread_y) % 360.0, view["pitch"] + spread_p, dist, conv)
    return out


MUTATIONS = {"silent_aim": silent_aim, "triggerbot": triggerbot, "smooth_lock": smooth_lock}


# --- scoring ------------------------------------------------------------------
@dataclass
class Trial:
    kind: str
    level: float
    flagged: bool
    suspicion: float
    label: str
    top_type: str | None
    right_type: bool
    metric: str

    @property
    def outcome(self) -> str:
        if self.level == 0:
            return "baseline"
        if self.flagged and self.label == "cheat_like":
            return "caught" if self.right_type else "caught (wrong type)"
        if self.label in ("cheat_like", "skill_or_cheat"):
            return "review" if self.right_type else "review (wrong type)"
        return "missed"


def _metric(kind: str, f) -> str:
    if kind == "silent_aim":
        return f"off-view hits {f.off_view_hits}/{f.hits}"
    if kind == "triggerbot":
        return (f"instant {f.instant_reactions}/{f.reaction_samples}, "
                f"median {f.reaction_median_ms:.0f} ms")
    return f"lock {f.lock_error_median:.2f} deg over {f.lock_samples} shots"


def trial(events: list[Event], cn: int, kind: str, level: float, seed: int = 0) -> Trial:
    mutated = MUTATIONS[kind](events, cn, level, seed=seed)
    feats = extract_features(mutated)
    f = feats[cn]
    v = judge(f)
    a = assess(f, v)
    top = a.likely_types[0].type if a.likely_types else None
    return Trial(kind, level, v.is_cheat, round(v.suspicion, 2), a.label, top,
                 top == EXPECTED_TYPE[kind], _metric(kind, f))


def sweep(events: list[Event], cn: int, kinds=None, levels=None, seed: int = 0) -> list[Trial]:
    out = []
    for kind in kinds or list(MUTATIONS):
        for level in (levels or LEVELS[kind]):
            out.append(trial(events, cn, kind, level, seed))
    return out


# --- database helpers -----------------------------------------------------------
def load_match(db: str, match_id: str) -> list[Event]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT payload FROM events WHERE match_id = ? ORDER BY id",
                           (match_id,)).fetchall()
    finally:
        con.close()
    if not rows:
        raise SystemExit(f"no events for match {match_id} in {db}")
    return _sorted([json.loads(r[0]) for r in rows])


def pick_player(events: list[Event], name: str | None) -> tuple[int, str]:
    names = {e["cn"]: e["name"] for e in events if e["type"] == "player_join"}
    if name:
        for cn, n in names.items():
            if n == name:
                return cn, n
        raise SystemExit(f"no player named {name!r}; players: {sorted(names.values())}")
    shots: dict[int, int] = {}
    for e in events:
        if e["type"] == "shot":
            shots[e["cn"]] = shots.get(e["cn"], 0) + 1
    if not shots:
        raise SystemExit("nobody fired in this match, so there is nothing to mutate")
    cn = max(shots, key=shots.get)
    return cn, names.get(cn, f"cn{cn}")


def save_match(db: str, events: list[Event], new_id: str) -> int:
    """Validate the mutated events with the collector's schema and store them
    under a new match_id, exactly like live telemetry."""
    from aegis_collector.schema import EventAdapter
    from aegis_collector.store import EventStore

    store = EventStore(db)
    try:
        store._conn.execute("DELETE FROM events WHERE match_id = ?", (new_id,))
        valid = [EventAdapter.validate_python({**e, "match_id": new_id}) for e in events]
        store.add_many(valid)
        return len(valid)
    finally:
        store.close()


def mutated_id(match_id: str, kind: str, level: float) -> str:
    lv = f"{level:g}".replace(".", "p")
    return f"{match_id}-mut-{kind}-{lv}"


def _print(trials: list[Trial], who: str, match_id: str) -> None:
    print(f"\nMutation sweep on {who} in {match_id}")
    kind = None
    for t in trials:
        if t.kind != kind:
            kind = t.kind
            print(f"\n  {kind}  (expect: {EXPECTED_TYPE[kind]})")
            print(f"  {'level':>8}  {'outcome':<22}{'label':<16}{'type':<14}{'susp':>5}  measured")
        lv = f"{t.level:g} {UNITS[t.kind]}"
        print(f"  {lv:>8}  {t.outcome:<22}{t.label:<16}{(t.top_type or '-'):<14}"
              f"{t.suspicion:>5.2f}  {t.metric}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/lab.db")
    ap.add_argument("--match", required=True, help="real match to mutate")
    ap.add_argument("--player", help="player name (default: whoever fired most)")
    ap.add_argument("--kind", choices=list(MUTATIONS), help="one mutation (default: all)")
    ap.add_argument("--level", type=float, help="one strength (with --kind)")
    ap.add_argument("--sweep", action="store_true", help="run every strength and print a table")
    ap.add_argument("--save", action="store_true", help="store the mutated match in the database")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    events = load_match(args.db, args.match)
    cn, name = pick_player(events, args.player)
    who = f"{name} (cn {cn})"

    if args.save:
        if not (args.kind and args.level is not None):
            raise SystemExit("--save needs --kind and --level")
        mutated = MUTATIONS[args.kind](events, cn, args.level, seed=args.seed)
        new_id = mutated_id(args.match, args.kind, args.level)
        n = save_match(args.db, mutated, new_id)
        print(f"saved {n} events as {new_id} ({args.kind} level {args.level:g} on {who})")
        print(f"next: python -m aegis_soc --db {args.db} --match {new_id} --watch")
        return

    kinds = [args.kind] if args.kind else None
    levels = [args.level] if args.level is not None else None
    trials = sweep(events, cn, kinds, levels, args.seed)
    if args.json:
        print(json.dumps([{**asdict(t), "outcome": t.outcome} for t in trials], indent=2))
    else:
        _print(trials, who, args.match)


if __name__ == "__main__":
    main()
