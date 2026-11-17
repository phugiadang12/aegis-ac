"""Tests for the AI SOC analyst.

These exercise the deterministic backend and the investigation tools end to
end, so the whole alert -> investigation -> case report pipeline is verified
with no API key and no network.
"""

import json

import pytest

from aegis_collector.sim_cheat import Cheat, simulate_mixed

from aegis_soc import (
    AlertQueue,
    HeuristicAnalyst,
    Investigation,
    MatchContext,
    build_analyst,
    triage_match,
)
from aegis_soc.report import TAXONOMY, CaseReport


def _match(profile, *, legit=6, cheaters=2, seconds=45, seed=5):
    ticks, labels = simulate_mixed(
        n_legit=legit, n_cheaters=cheaters, profile=profile,
        seconds=seconds, seed=seed,
    )
    return [ev for tick in ticks for ev in tick], labels


def _a_flagged_cn(ctx: MatchContext) -> int:
    return next(v.cn for v in ctx.verdicts.values() if v.is_cheat)


# --- investigation tools --------------------------------------------------
def test_overview_exposes_detector_rule_hits():
    events, _ = _match(Cheat.AIMBOT)
    ctx = MatchContext.from_events(events)
    cn = _a_flagged_cn(ctx)
    ov = Investigation(ctx).overview(cn)
    assert ov["cn"] == cn
    assert ov["detector"]["flagged"] is True
    assert ov["detector"]["rule_hits"], "a flagged player must carry rule hits"


def test_all_tool_outputs_are_json_serialisable():
    """The LLM backend hands these to the model as JSON, so every field must
    survive json.dumps (the z-score 'inf' sentinel is the tricky one)."""
    events, _ = _match(Cheat.ESP)
    ctx = MatchContext.from_events(events)
    inv = Investigation(ctx)
    cn = _a_flagged_cn(ctx)
    for payload in (inv.roster(), inv.overview(cn), inv.baseline(cn),
                    inv.turn_timeline(cn), inv.honeypot(cn)):
        json.dumps(payload)  # raises if anything is non-serialisable


def test_baseline_puts_cheater_far_above_the_cohort():
    events, _ = _match(Cheat.AIMBOT)
    ctx = MatchContext.from_events(events)
    cn = _a_flagged_cn(ctx)
    base = Investigation(ctx).baseline(cn)
    scores = [c["z_score"] for c in base["comparisons"]]
    # at least one metric is either off-the-scale or many sigmas out
    assert any(z == "inf" or (isinstance(z, (int, float)) and z >= 3) for z in scores)


def test_honeypot_tool_finds_blind_shots_for_esp():
    events, labels = _match(Cheat.ESP)
    ctx = MatchContext.from_events(events)
    inv = Investigation(ctx)
    cheater = _a_flagged_cn(ctx)
    hp = inv.honeypot(cheater)
    assert hp["phantom_tracked"] is True
    assert hp["blind_shots_at_phantom"] >= 1
    # a legit player should not be shooting the invisible phantom blind
    legit_cn = next(cn for cn, l in labels.items() if l == "legit")
    assert inv.honeypot(legit_cn)["blind_shots_at_phantom"] <= 2


def test_turn_timeline_catches_the_aimbot_snap():
    events, _ = _match(Cheat.AIMBOT)
    ctx = MatchContext.from_events(events)
    cn = _a_flagged_cn(ctx)
    turns = Investigation(ctx).turn_timeline(cn)
    assert turns["sharpest_turns"][0]["deg_per_s"] > 900


# --- alert queue & triage -------------------------------------------------
def test_queue_orders_most_suspicious_first():
    events, _ = _match(Cheat.ESP)
    ctx = MatchContext.from_events(events)
    q = AlertQueue()
    assert q.ingest(ctx) >= 1
    scores = [a.suspicion for a in q]
    assert scores == sorted(scores, reverse=True)


def test_triage_writes_one_report_per_alert():
    events, _ = _match(Cheat.ESP)
    ctx = MatchContext.from_events(events)
    n_flagged = sum(v.is_cheat for v in ctx.verdicts.values())
    reports = triage_match(events, analyst=HeuristicAnalyst())
    assert len(reports) == n_flagged
    for r in reports:
        assert isinstance(r, CaseReport)
        assert r.disposition in {"ban", "shadow", "monitor", "clear"}
        assert 0.0 <= r.confidence <= 1.0
        assert r.evidence


def test_pure_legit_match_raises_no_alerts():
    events, _ = _match(Cheat.LEGIT, cheaters=0)
    assert triage_match(events, analyst=HeuristicAnalyst()) == []


@pytest.mark.parametrize("profile", [c for c in Cheat if c is not Cheat.LEGIT])
def test_report_names_the_right_cheat_family(profile):
    events, _ = _match(profile)
    reports = triage_match(events, analyst=HeuristicAnalyst())
    assert reports, f"{profile.value} produced no alerts"
    cats = {r.category for r in reports}
    assert cats <= set(TAXONOMY), f"unknown category in {cats}"


def test_esp_case_recommends_enforcement():
    events, _ = _match(Cheat.ESP)
    reports = triage_match(events, analyst=HeuristicAnalyst())
    esp = [r for r in reports if r.category == "esp"]
    assert esp, "the ESP wallhacker should be caught and classified as esp"
    top = max(esp, key=lambda r: r.confidence)
    assert top.disposition in {"ban", "shadow"}
    assert top.confidence >= 0.9


def test_case_report_renders_with_evidence():
    events, _ = _match(Cheat.TRIGGERBOT)
    report = triage_match(events, analyst=HeuristicAnalyst())[0]
    card = report.render()
    assert report.name in card
    assert "Evidence:" in card and "Recommendation:" in card


# --- backend selection ----------------------------------------------------
def test_build_analyst_is_deterministic_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(build_analyst(), HeuristicAnalyst)
