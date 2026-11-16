"""Checks that each synthetic cheat leaves a telemetry signature distinct from
legit play. These are the ground truths the blue-team detector will be scored
against, so if a signature here is weak the detector's job is impossible."""

import math

import pytest

from aegis_collector.schema import EventAdapter
from aegis_collector.sim_cheat import Cheat, simulate_mixed


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def _collect(profile, **kw):
    """Run a mixed match; return (events, labels)."""
    kw.setdefault("seconds", 40)
    kw.setdefault("seed", 11)
    ticks, labels = simulate_mixed(n_legit=6, n_cheaters=2, profile=profile, **kw)
    events = [ev for tick in ticks for ev in tick]
    return events, labels


def _max_turn_rate(events, cn, tick_hz=30):
    """Biggest single-tick angular velocity (deg/s) for one player."""
    yaws = [(e["ts"], e["yaw"]) for e in events if e["type"] == "tick" and e["cn"] == cn]
    worst = 0.0
    for (t0, y0), (t1, y1) in zip(yaws, yaws[1:]):
        dt = (t1 - t0) / 1000.0
        if dt > 0:
            worst = max(worst, abs(_wrap180(y1 - y0)) / dt)
    return worst


def test_all_generated_events_are_valid():
    events, _ = _collect(Cheat.AIMBOT)
    for ev in events:
        EventAdapter.validate_python(ev)


def test_labels_mark_last_players_as_cheaters():
    _, labels = _collect(Cheat.AIMBOT)
    assert labels[6] == "aimbot" and labels[7] == "aimbot"
    assert all(labels[cn] == "legit" for cn in range(6))


def test_aimbot_has_impossible_turn_rate():
    events, _ = _collect(Cheat.AIMBOT)
    legit = max(_max_turn_rate(events, cn) for cn in range(6))
    cheat = max(_max_turn_rate(events, cn) for cn in (6, 7))
    # aimbot snaps in one tick; a human's capped turn speed can't match it
    assert cheat > legit * 3


def test_aimbot_lands_far_more_shots():
    events, _ = _collect(Cheat.AIMBOT)

    def hit_rate(cn):
        shots = sum(e["type"] == "shot" and e["cn"] == cn for e in events)
        hits = sum(e["type"] == "damage" and e["attacker"] == cn for e in events)
        return hits / shots if shots else 0.0

    legit = max(hit_rate(cn) for cn in range(6))
    cheat = min(hit_rate(cn) for cn in (6, 7))
    assert cheat > legit


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def test_match_emits_moving_honeypot():
    ticks, _ = simulate_mixed(n_legit=6, n_cheaters=2, profile=Cheat.ESP,
                              seconds=20, seed=5)
    hp = [ev for tick in ticks for ev in tick if ev["type"] == "honeypot"]
    assert len(hp) > 100
    xs = {round(e["pos"]["x"], 1) for e in hp}
    assert len(xs) > 10  # the phantom actually moves, not a fixed point


def test_only_esp_players_aim_at_the_honeypot():
    """The telemetry tell the detector relies on: cheaters fire at the phantom,
    legit players (who were never told it exists) do not."""
    import math
    ANGLE = 6.0
    ticks, labels = simulate_mixed(n_legit=6, n_cheaters=2, profile=Cheat.ESP,
                                   seconds=45, seed=5)
    events = [ev for tick in ticks for ev in tick]
    ghost = {e["ts"]: (e["pos"]["x"], e["pos"]["y"])
             for e in events if e["type"] == "honeypot"}
    pos = {}
    for e in events:
        if e["type"] == "tick":
            pos.setdefault(e["ts"], {})[e["cn"]] = (e["pos"]["x"], e["pos"]["y"])
    at_ghost = {}
    for e in events:
        if e["type"] != "shot" or e["ts"] not in ghost:
            continue
        ox, oy = e["origin"]["x"], e["origin"]["y"]
        gx, gy = ghost[e["ts"]]
        aim = math.degrees(math.atan2(e["target"]["y"] - oy, e["target"]["x"] - ox))
        if abs(_wrap180(math.degrees(math.atan2(gy - oy, gx - ox)) - aim)) > ANGLE:
            continue
        enemy_near = any(
            abs(_wrap180(math.degrees(math.atan2(py - oy, px - ox)) - aim)) <= ANGLE
            for cn, (px, py) in pos.get(e["ts"], {}).items() if cn != e["cn"]
        )
        if not enemy_near:
            at_ghost[e["cn"]] = at_ghost.get(e["cn"], 0) + 1
    cheater_hits = sum(at_ghost.get(cn, 0) for cn, l in labels.items() if l != "legit")
    legit_hits = sum(at_ghost.get(cn, 0) for cn, l in labels.items() if l == "legit")
    assert cheater_hits >= 3
    assert legit_hits <= 2  # the occasional coincidence, below the flag threshold


def test_triggerbot_is_near_perfectly_accurate():
    """A triggerbot only pulls the trigger on a near-exact alignment, so it
    fires less often than a human but lands almost every shot — an
    inhuman per-shot accuracy that is its telemetry signature."""
    events, _ = _collect(Cheat.TRIGGERBOT)

    def hit_rate(cn):
        shots = sum(e["type"] == "shot" and e["cn"] == cn for e in events)
        hits = sum(e["type"] == "damage" and e["attacker"] == cn for e in events)
        return hits / shots if shots else 0.0

    legit = max(hit_rate(cn) for cn in range(6))
    cheat = min(hit_rate(cn) for cn in (6, 7))
    assert cheat > 0.95          # lands essentially everything it fires
    assert cheat > legit * 1.5   # far above any human


@pytest.mark.parametrize("profile", list(Cheat))
def test_every_profile_runs_and_produces_combat(profile):
    n_cheat = 0 if profile is Cheat.LEGIT else 2
    ticks, _ = simulate_mixed(
        n_legit=6, n_cheaters=n_cheat, profile=profile, seconds=30, seed=3
    )
    types = [ev["type"] for tick in ticks for ev in tick]
    assert types.count("shot") > 20
    assert "tick" in types
