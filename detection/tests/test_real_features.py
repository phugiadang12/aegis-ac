"""Unit tests for the real-game features, built from small hand-written
AssaultCube-style event streams (match_id ``ac-...``, the game's own yaw
convention). Each test is one situation a SOC reviewer cares about."""

from aegis_detection.classify import assess
from aegis_detection.features import aim_angles, extract_features
from aegis_detection.rules import judge

MID = "ac-test-1"
TICK_MS = 40.0                         # real AssaultCube clients update ~25 Hz
SHOOTER, ENEMY = 0, 1


def _tick(ts, cn, x, y, yaw, pitch=0.0, z=0.0):
    return {"ts": ts, "match_id": MID, "type": "tick", "cn": cn,
            "pos": {"x": x, "y": y, "z": z}, "yaw": yaw, "pitch": pitch, "alive": True}


def _shot(ts, cn, origin, target):
    return {"ts": ts, "match_id": MID, "type": "shot", "cn": cn, "weapon": "g6",
            "origin": {"x": origin[0], "y": origin[1], "z": 0.0},
            "target": {"x": target[0], "y": target[1], "z": 0.0}}


def _damage(ts, attacker, target):
    return {"ts": ts, "match_id": MID, "type": "damage", "attacker": attacker,
            "target": target, "weapon": "g6", "amount": 20, "headshot": False}


def _join():
    return [{"ts": 0.0, "match_id": MID, "type": "player_join", "cn": c, "name": n}
            for c, n in ((SHOOTER, "shooter"), (ENEMY, "enemy"))]


def _yaw_to(src, dst):
    return aim_angles({"x": src[0], "y": src[1], "z": 0}, {"x": dst[0], "y": dst[1], "z": 0}, "ac")[0]


def _engagements(n, reaction_ticks, shot_angle_off=0.0, hit=True, lock_off=0.0):
    """n separate engagements: the shooter looks away, turns onto the enemy,
    waits ``reaction_ticks`` ticks, then fires once."""
    me, foe = (0.0, 0.0), (0.0, -100.0)
    on_yaw = _yaw_to(me, foe)
    ev, ts = _join(), 0.0
    for _ in range(n):
        # look away and back at human speed (12 deg/tick = 300 deg/s), no shots
        offsets = [min(90, 12 * k) for k in range(1, 11)] + [90 - 12 * k for k in range(1, 8)]
        for off in offsets:
            ts += TICK_MS
            ev += [_tick(ts, ENEMY, *foe, 0.0), _tick(ts, SHOOTER, *me, (on_yaw + off) % 360)]
        for _ in range(reaction_ticks + 1):      # crosshair on the enemy
            ts += TICK_MS
            ev += [_tick(ts, ENEMY, *foe, 0.0),
                   _tick(ts, SHOOTER, *me, (on_yaw + lock_off) % 360)]
        # the shot leaves shot_angle_off degrees away from the view
        shot_yaw = (on_yaw + lock_off + shot_angle_off) % 360
        far = _point_at(me, shot_yaw)
        ev.append(_shot(ts + 1, SHOOTER, me, far))
        if hit:
            ev.append(_damage(ts + 3, SHOOTER, ENEMY))
    return ev


def _point_at(src, yaw, dist=100.0):
    """Inverse of the AssaultCube yaw convention: a point ``dist`` away at ``yaw``."""
    import math
    r = math.radians(yaw)
    return (src[0] + math.sin(r) * dist, src[1] - math.cos(r) * dist)


def test_ac_convention_points_at_enemy():
    me, foe = (0.0, 0.0), (37.0, -12.0)
    yaw = _yaw_to(me, foe)
    px, py = _point_at(me, yaw)
    assert abs(_yaw_to(me, (px, py)) - yaw) < 1e-6


def test_respawn_teleport_is_not_a_turn():
    ev = _join() + [
        _tick(40, SHOOTER, 0, 0, 10.0),
        _tick(80, SHOOTER, 0.5, 0, 12.0),
        _tick(120, SHOOTER, 58.0, 30.0, 190.0),     # respawn: jumped + view reset
        _tick(160, SHOOTER, 58.5, 30.0, 191.0),
    ]
    f = extract_features(ev)[SHOOTER]
    assert f.teleports == 1
    assert f.max_turn_rate < 100                    # the 180 deg reset is ignored


def test_silent_aim_hits_are_cheat_like():
    f = extract_features(_engagements(4, reaction_ticks=5, shot_angle_off=40.0))[SHOOTER]
    assert f.off_view_hits == 4
    v = judge(f)
    assert v.is_cheat and v.category == "silent_aim"
    a = assess(f, v)
    assert a.label == "cheat_like"
    assert a.likely_types[0].type == "silent_aim"
    assert any("crosshair" in x for x in a.review_focus)


def test_normal_spread_is_not_silent_aim():
    f = extract_features(_engagements(8, reaction_ticks=5, shot_angle_off=5.0))[SHOOTER]
    assert f.off_view_hits == 0


def test_instant_reactions_point_to_triggerbot():
    f = extract_features(_engagements(8, reaction_ticks=0))[SHOOTER]
    assert f.reaction_samples == 8
    assert f.instant_reaction_rate == 1.0
    v = judge(f)
    assert v.is_cheat and v.category == "triggerbot"
    assert assess(f, v).label == "cheat_like"


def test_human_reaction_time_is_a_human_signal():
    # 5 ticks x 40 ms = 200 ms: a normal human reaction
    f = extract_features(_engagements(8, reaction_ticks=5, lock_off=3.0))[SHOOTER]
    assert 180 <= f.reaction_median_ms <= 220
    v = judge(f)
    assert not any(h.rule == "instant_reaction" for h in v.hits)
    assert any("reaction" in s for s in assess(f, v).human_signals)


def test_tight_lock_alone_is_skill_or_cheat_not_a_ban():
    # human reaction time but a crosshair dead-centre on every shot
    # (shots miss so the separate accuracy rule stays out of the picture)
    f = extract_features(_engagements(10, reaction_ticks=5, lock_off=0.5, hit=False))[SHOOTER]
    v = judge(f)
    assert [h.rule for h in v.hits] == ["tight_lock"]
    assert not v.is_cheat                           # provisional rule never flags alone
    assert assess(f, v).label == "skill_or_cheat"


def test_perfect_accuracy_with_human_timing_goes_to_review_not_ban():
    """The 'pro player' case: lands everything, but reaction and turn speed are
    human. The SOC agent must send it to a human, never straight to a ban."""
    from aegis_soc.analyst import HeuristicAnalyst
    from aegis_soc.evidence import MatchContext

    ctx = MatchContext.from_events(
        _engagements(10, reaction_ticks=5, lock_off=3.0), match_id=MID)
    v = ctx.verdicts[SHOOTER]
    assert v.is_cheat and v.category == "triggerbot"        # inhuman_accuracy rule
    report = HeuristicAnalyst().investigate(ctx, SHOOTER)
    assert report.disposition == "monitor"
    assert "none is impossible for a human" in report.skill_check
    assert report.review_focus
