"""Tests for the alert notifier (Discord + pluggable channels).

A fake sender captures what would be posted, so nothing hits the network.
"""

import pytest

from aegis_soc.notify import (
    DiscordWebhook,
    Notification,
    Notifier,
    NotifyResult,
)
from aegis_soc.report import CaseReport

WEBHOOK = "https://discord.com/api/webhooks/123/abc"


def _case(**over) -> CaseReport:
    base = dict(
        cn=7, name="p07", category="esp", confidence=0.95, disposition="ban",
        title="esp - p07", summary="Wallhacked.", evidence=["aimed at the phantom 8x"],
        recommendation="Approve a ban.",
    )
    base.update(over)
    return CaseReport(**base)


class Capture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, payload: dict) -> None:
        self.calls.append((url, payload))


def test_discord_payload_has_embed_with_disposition_color():
    cap = Capture()
    ch = DiscordWebhook(WEBHOOK, sender=cap)
    ch.send(Notification.from_case(_case(), "scrim-01"))
    url, payload = cap.calls[0]
    assert url == WEBHOOK
    embed = payload["embeds"][0]
    assert "p07" in embed["title"] or any(f["value"].startswith("p07") for f in embed["fields"])
    assert embed["color"] == 0xEF4444  # ban -> red
    names = {f["name"] for f in embed["fields"]}
    assert {"Player", "Category", "Confidence", "Evidence", "Recommendation"} <= names


def test_disposition_changes_embed_color():
    cap = Capture()
    DiscordWebhook(WEBHOOK, sender=cap).send(
        Notification.from_case(_case(disposition="monitor"), "m"))
    assert cap.calls[0][1]["embeds"][0]["color"] == 0x38BDF8


def test_discord_requires_https():
    with pytest.raises(ValueError):
        DiscordWebhook("http://discord.com/api/webhooks/1/x")


def test_notifier_fans_out_to_all_channels():
    cap = Capture()
    notifier = Notifier([DiscordWebhook(WEBHOOK, sender=cap)])
    results = notifier.notify(_case(), "scrim-01")
    assert results == [NotifyResult("discord", True)]
    assert len(cap.calls) == 1


def test_one_failing_channel_does_not_break_the_others():
    cap = Capture()

    class Boom:
        name = "boom"
        def send(self, note):
            raise RuntimeError("webhook down")

    notifier = Notifier([Boom(), DiscordWebhook(WEBHOOK, sender=cap)])
    results = notifier.notify(_case(), "m")
    assert results[0].ok is False and "down" in (results[0].error or "")
    assert results[1].ok is True
    assert len(cap.calls) == 1  # the healthy channel still delivered


def test_from_env_builds_configured_channels(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", WEBHOOK)
    monkeypatch.setenv("AEGIS_NOTIFY_CONSOLE", "1")
    assert set(Notifier.from_env().configured) == {"discord", "console"}


def test_from_env_is_empty_without_config(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("AEGIS_NOTIFY_CONSOLE", raising=False)
    assert Notifier.from_env().configured == []
