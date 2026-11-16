"""The detector must flag cheaters and leave legit players alone, across every
profile, scored against the simulator's ground-truth labels."""

import pytest

from aegis_collector.sim_cheat import Cheat, simulate_mixed
from aegis_detection.evaluate import evaluate
from aegis_detection.features import extract_features
from aegis_detection.rules import CHEAT_THRESHOLD, judge_all


def _run(profile, seed=42, seconds=45, legit=6, cheaters=2):
    ticks, labels = simulate_mixed(
        n_legit=legit, n_cheaters=cheaters, profile=profile,
        seconds=seconds, seed=seed,
    )
    events = [ev for tick in ticks for ev in tick]
    verdicts = {v.cn: v for v in judge_all(extract_features(events))}
    return verdicts, labels


def test_aimbot_flagged_with_snap_reason():
    verdicts, labels = _run(Cheat.AIMBOT)
    cheats = [v for cn, v in verdicts.items() if labels[cn] == "aimbot"]
    assert cheats and all(v.is_cheat for v in cheats)
    # the explanation should name the impossible snap
    assert any("snapped" in h.reason for v in cheats for h in v.hits)


@pytest.mark.parametrize("profile", [c for c in Cheat if c is not Cheat.LEGIT])
def test_catches_every_cheat_profile(profile):
    verdicts, labels = _run(profile)
    for cn, label in labels.items():
        if label != "legit":
            assert verdicts[cn].is_cheat, f"missed {label} (cn {cn})"


@pytest.mark.parametrize("profile", [c for c in Cheat if c is not Cheat.LEGIT])
def test_no_false_positive_on_legit(profile):
    verdicts, labels = _run(profile)
    for cn, label in labels.items():
        if label == "legit":
            v = verdicts[cn]
            assert not v.is_cheat, (
                f"legit cn {cn} flagged as {v.category} "
                f"(suspicion {v.suspicion}) in a {profile.value} match"
            )


def test_pure_legit_match_has_no_flags():
    verdicts, labels = _run(Cheat.LEGIT, cheaters=0, legit=8)
    assert all(not v.is_cheat for v in verdicts.values())


def test_profile_signature_present_in_reasons():
    """The cheat's own signature must appear among a flagged player's rule hits.
    Categories can co-occur (an ESP that snap-aims also trips the aimbot rule),
    so we check the expected category is *somewhere* in the hits, not that it
    ranks first."""
    expect = {
        Cheat.AIMBOT: {"aimbot"},
        Cheat.TRIGGERBOT: {"triggerbot", "aimbot"},
        Cheat.HUMANISED: {"humanised_aimbot", "triggerbot", "aimbot"},
        Cheat.ESP: {"esp"},
    }
    for profile, expected in expect.items():
        verdicts, labels = _run(profile)
        for cn, label in labels.items():
            if label != "legit":
                categories = {h.category for h in verdicts[cn].hits}
                assert categories & expected, (
                    f"{profile.value} cn {cn}: hits {categories} "
                    f"lack any of {expected}"
                )


def test_suspicion_never_exceeds_one():
    for profile in Cheat:
        verdicts, _ = _run(profile, cheaters=0 if profile is Cheat.LEGIT else 2)
        assert all(0.0 <= v.suspicion <= 1.0 for v in verdicts.values())


def test_evaluate_scores_high_detection_low_fp():
    results = evaluate(matches=6, seconds=40)
    overall = results["OVERALL"]
    assert overall.detection_rate >= 0.90
    assert overall.fp_rate <= 0.05
