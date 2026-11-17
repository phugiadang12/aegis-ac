"""Push SOC case reports out to chat platforms.

When the analyst confirms a cheater, the anti-cheat team wants to know without
watching the dashboard. This module turns a ``CaseReport`` into an alert and
fans it out over pluggable channels. Discord (incoming webhook) is implemented;
the ``NotifyChannel`` protocol keeps the door open for Zalo, Slack, a Grafana
contact point, or any webhook.

No third-party SDK and no new dependency: posting is a plain HTTPS request via
the standard library, behind an injectable sender so tests never touch the
network. Webhook URLs are read from the environment and never logged.
"""

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol

from .report import CaseReport

# Discord embed accent per disposition (decimal RGB).
_DISPO_COLOR = {
    "ban": 0xEF4444,
    "shadow": 0xF59E0B,
    "monitor": 0x38BDF8,
    "clear": 0x22C55E,
}

Sender = Callable[[str, dict], None]


# Discord (and its Cloudflare front) rejects requests with no real User-Agent,
# so send a generic client identifier — never anything that identifies the user.
_USER_AGENT = "AegisAC/0.1 (+anti-cheat SOC notifier)"


def _http_post(url: str, payload: dict, timeout: float = 5.0) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (https enforced by channel)
        resp.read()


@dataclass
class Notification:
    match_id: str
    cn: int
    name: str
    category: str
    confidence: float
    disposition: str
    title: str
    summary: str
    evidence: list[str]
    recommendation: str

    @classmethod
    def from_case(cls, case: CaseReport, match_id: str) -> "Notification":
        return cls(
            match_id=match_id, cn=case.cn, name=case.name, category=case.category,
            confidence=case.confidence, disposition=case.disposition,
            title=case.title, summary=case.summary, evidence=case.evidence,
            recommendation=case.recommendation,
        )


class NotifyChannel(Protocol):
    name: str
    def send(self, note: Notification) -> None: ...


class DiscordWebhook:
    """Posts a rich embed to a Discord channel via an incoming webhook."""

    name = "discord"

    def __init__(self, url: str, sender: Sender | None = None) -> None:
        if not url.startswith("https://"):
            raise ValueError("Discord webhook URL must be https")
        self.url = url
        self._send = sender or _http_post

    def build_payload(self, note: Notification) -> dict:
        evidence = "\n".join(f"• {e}" for e in note.evidence[:6]) or "—"
        return {
            "username": "Aegis AC",
            "embeds": [{
                "title": f"⚠ {note.title}",
                "description": note.summary,
                "color": _DISPO_COLOR.get(note.disposition, 0x94A3B8),
                "fields": [
                    {"name": "Player", "value": f"{note.name} (cn {note.cn})", "inline": True},
                    {"name": "Category", "value": note.category, "inline": True},
                    {"name": "Confidence", "value": f"{note.confidence*100:.0f}%", "inline": True},
                    {"name": "Disposition", "value": note.disposition.upper(), "inline": True},
                    {"name": "Match", "value": note.match_id, "inline": True},
                    {"name": "Evidence", "value": evidence[:1024], "inline": False},
                    {"name": "Recommendation", "value": note.recommendation[:1024], "inline": False},
                ],
                "footer": {"text": "Aegis AC — a human approves every ban"},
            }],
        }

    def send(self, note: Notification) -> None:
        self._send(self.url, self.build_payload(note))


class ConsoleChannel:
    """Prints the alert instead of sending it — handy for demos with no webhook."""

    name = "console"

    def __init__(self, stream=None) -> None:
        self._stream = stream

    def send(self, note: Notification) -> None:
        line = (f"[ALERT] {note.disposition.upper()} {note.name} "
                f"({note.category} {note.confidence*100:.0f}%) in {note.match_id}")
        print(line, file=self._stream)


@dataclass
class NotifyResult:
    channel: str
    ok: bool
    error: str | None = None


class Notifier:
    """Fans a case out to every configured channel; never raises on a channel
    failure, so a down webhook can't break the request that triggered it."""

    def __init__(self, channels: list[NotifyChannel] | None = None) -> None:
        self.channels = channels or []

    @property
    def configured(self) -> list[str]:
        return [c.name for c in self.channels]

    def notify(self, case: CaseReport, match_id: str) -> list[NotifyResult]:
        note = Notification.from_case(case, match_id)
        results = []
        for ch in self.channels:
            try:
                ch.send(note)
                results.append(NotifyResult(ch.name, True))
            except Exception as exc:
                results.append(NotifyResult(ch.name, False, str(exc)))
        return results

    @classmethod
    def from_env(cls) -> "Notifier":
        """Build channels from the environment:
        DISCORD_WEBHOOK_URL -> Discord; AEGIS_NOTIFY_CONSOLE=1 -> console echo."""
        channels: list[NotifyChannel] = []
        url = os.environ.get("DISCORD_WEBHOOK_URL")
        if url:
            channels.append(DiscordWebhook(url))
        if os.environ.get("AEGIS_NOTIFY_CONSOLE") == "1":
            channels.append(ConsoleChannel())
        return cls(channels)
