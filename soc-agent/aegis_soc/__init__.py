"""Aegis AC — AI SOC analyst (Phase 4).

Investigates detector alerts with the same tools a human analyst would use and
files a reviewable case report. Runs fully offline with a deterministic backend;
set ANTHROPIC_API_KEY to let a Claude agent drive the investigation.
"""

from .analyst import HeuristicAnalyst, LLMAnalyst, build_analyst
from .enforcement import BanRecord, BanWave, LoggingKickExecutor
from .evidence import Investigation, MatchContext
from .notify import DiscordWebhook, Notification, Notifier
from .report import TAXONOMY, CaseReport
from .triage import Alert, AlertQueue, triage_match

__all__ = [
    "HeuristicAnalyst", "LLMAnalyst", "build_analyst",
    "Investigation", "MatchContext",
    "CaseReport", "TAXONOMY",
    "Alert", "AlertQueue", "triage_match",
    "BanWave", "BanRecord", "LoggingKickExecutor",
    "Notifier", "DiscordWebhook", "Notification",
]
