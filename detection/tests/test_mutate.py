"""Telemetry mutation: each mutation must leave exactly the footprint of its
cheat, never touch the original events, and save as a valid new match."""

import json
import sqlite3

from test_real_features import SHOOTER, _engagements

from aegis_detection.classify import assess
from aegis_detection.features import extract_features
from aegis_detection.mutate import (
    mutated_id,
    save_match,
    silent_aim,
    smooth_lock,
    sweep,
    triggerbot,
)
from aegis_detection.rules import judge


def _assess(events):
    f = extract_features(events)[SHOOTER]
    return f, assess(f, judge(f))


def test_silent_aim_mutation_is_caught_and_typed():
    # 30 deg: this fixture turns 12 deg/tick right after each shot, and a shot is
    # only off-view when it is far from the view on BOTH sides of it
    base = _engagements(6, reaction_ticks=5, lock_off=3.0)
    f, a = _assess(silent_aim(base, SHOOTER, 30))
    assert f.off_view_hits == 6
    assert a.label == "cheat_like" and a.likely_types[0].type == "silent_aim"


def test_small_silent_aim_offset_stays_inside_normal_spread():
    f, _ = _assess(silent_aim(_engagements(6, reaction_ticks=5), SHOOTER, 5))
    assert f.off_view_hits == 0


def test_triggerbot_mutation_creates_one_tick_reactions():
    base = _engagements(10, reaction_ticks=5, lock_off=3.0, hit=False)
    f0, _ = _assess(base)
    assert f0.instant_reactions == 0
    f, a = _assess(triggerbot(base, SHOOTER, 1.0))
    assert f.instant_reaction_rate == 1.0 and f.reaction_samples == 10
    assert a.likely_types[0].type == "triggerbot"


def test_smooth_lock_pulls_the_crosshair_onto_the_enemy():
    base = _engagements(10, reaction_ticks=5, lock_off=3.0, hit=False)
    f0, _ = _assess(base)
    f, _ = _assess(smooth_lock(base, SHOOTER, 1.0))
    assert f0.lock_error_median > 2.5
    assert f.lock_error_median < 0.1


def test_mutations_never_change_the_original_events():
    base = _engagements(4, reaction_ticks=5)
    snapshot = json.dumps(base, sort_keys=True)
    for mutate, level in ((silent_aim, 30), (triggerbot, 1.0), (smooth_lock, 1.0)):
        mutate(base, SHOOTER, level)
    assert json.dumps(base, sort_keys=True) == snapshot


def test_sweep_has_a_baseline_row_per_mutation():
    trials = sweep(_engagements(4, reaction_ticks=5), SHOOTER)
    assert {t.kind for t in trials if t.outcome == "baseline"} == {
        "silent_aim", "triggerbot", "smooth_lock"}


def test_save_writes_a_valid_new_match(tmp_path):
    db = str(tmp_path / "lab.db")
    base = _engagements(3, reaction_ticks=5)
    new_id = mutated_id("ac-test-1", "silent_aim", 20)
    assert new_id == "ac-test-1-mut-silent_aim-20"
    n = save_match(db, silent_aim(base, SHOOTER, 20), new_id)
    assert n == len(base)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT DISTINCT match_id FROM events").fetchall()
    con.close()
    assert rows == [(new_id,)]
