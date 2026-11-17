"""Tests for the dashboard analysis API."""

import pytest
from fastapi.testclient import TestClient

from aegis_soc.analyst import HeuristicAnalyst
from aegis_soc.api import create_app
from aegis_soc.notify import DiscordWebhook, Notifier


@pytest.fixture
def client():
    app = create_app(analyst=HeuristicAnalyst())  # deterministic, no API key
    with TestClient(app) as c:
        yield c


@pytest.fixture
def notified():
    """Client whose notifier posts to a captured Discord webhook."""
    calls: list = []
    notifier = Notifier([DiscordWebhook(
        "https://discord.com/api/webhooks/1/x",
        sender=lambda url, payload: calls.append((url, payload)))])
    app = create_app(analyst=HeuristicAnalyst(), notifier=notifier)
    with TestClient(app) as c:
        yield c, calls


def test_health_reports_seeded_matches(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["matches"] == 5


def test_matches_listing_marks_the_clean_match(client):
    matches = {m["match_id"]: m for m in client.get("/api/matches").json()}
    assert matches["scrim-05-clean"]["flagged"] == 0
    assert matches["scrim-01-esp"]["flagged"] >= 1


def test_alerts_are_sorted_and_include_the_esp_match(client):
    alerts = client.get("/api/alerts").json()
    assert alerts, "the seeded matches should raise alerts"
    scores = [a["suspicion"] for a in alerts]
    assert scores == sorted(scores, reverse=True)
    assert any(a["match_id"] == "scrim-01-esp" and a["category"] == "esp"
               for a in alerts)


def test_case_endpoint_returns_a_report(client):
    alert = client.get("/api/alerts").json()[0]
    case = client.get(
        f"/api/matches/{alert['match_id']}/cases/{alert['cn']}").json()
    assert case["cn"] == alert["cn"]
    assert case["disposition"] in {"ban", "shadow", "monitor", "clear"}
    assert case["evidence"]


def test_replay_has_trajectories_shots_and_honeypot(client):
    replay = client.get("/api/matches/scrim-01-esp/replay").json()
    assert replay["map_size"] > 0
    assert replay["players"]
    # every player has a movement trajectory
    assert all(str(p["cn"]) in replay["trajectories"] for p in replay["players"])
    assert replay["shots"]
    assert replay["honeypot"], "the ESP match tracks a honeypot phantom"


def test_ban_wave_queue_and_release_flow(client):
    alert = client.get("/api/alerts").json()[0]
    mid, cn = alert["match_id"], alert["cn"]

    snap = client.post(f"/api/banwave/queue/{mid}/{cn}").json()
    assert any(r["cn"] == cn and r["match_id"] == mid for r in snap["queued"])

    # the alert now reports it is queued for a ban
    a2 = next(a for a in client.get("/api/alerts").json()
              if a["match_id"] == mid and a["cn"] == cn)
    assert a2["queued_for_ban"] is True

    released = client.post("/api/banwave/release").json()
    assert any(r["cn"] == cn for r in released["released"])
    assert released["queued"] == []
    assert any(r["cn"] == cn for r in released["history"])
    assert released["enforcement_log"]


def test_unknown_match_is_404(client):
    assert client.get("/api/matches/nope/replay").status_code == 404


def test_queueing_a_ban_pushes_a_discord_alert(notified):
    client, calls = notified
    alert = client.get("/api/alerts").json()[0]
    client.post(f"/api/banwave/queue/{alert['match_id']}/{alert['cn']}")
    assert len(calls) == 1
    _, payload = calls[0]
    assert payload["embeds"][0]["fields"], "a Discord embed should have been posted"
    status = client.get("/api/notify/status").json()
    assert status["channels"] == ["discord"] and status["sent"] == 1


def test_notify_test_endpoint_sends_top_case(notified):
    client, calls = notified
    body = client.post("/api/notify/test").json()
    assert body["sent_to"] == ["discord"]
    assert len(calls) == 1


def test_notify_test_without_channels_is_400(client):
    assert client.post("/api/notify/test").status_code == 400
