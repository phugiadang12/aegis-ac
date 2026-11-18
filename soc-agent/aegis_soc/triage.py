"""Alert queue and match-level triage.

Glue between the detector and the analyst: turn a match's verdicts into an
ordered alert queue, then run the analyst over each alert to produce case
reports a human can review.
"""

from dataclasses import dataclass
from typing import Any

from .analyst import Analyst, HeuristicAnalyst
from .evidence import MatchContext
from .report import CaseReport


@dataclass(order=True)
class Alert:
    # ordered so the queue pops the most suspicious first
    suspicion: float
    cn: int
    name: str
    category: str | None

    @property
    def priority(self) -> str:
        return "high" if self.suspicion >= 0.9 else "medium"


class AlertQueue:
    """The flagged players from one or more matches, highest suspicion first."""

    def __init__(self) -> None:
        self._alerts: list[Alert] = []

    def ingest(self, ctx: MatchContext, include_watch: bool = False) -> int:
        """Queue flagged players. With ``include_watch`` also queue players who
        tripped a rule but stayed under the flag threshold (the "watch" tier),
        so a reviewer sees borderline cases such as a very good player."""
        added = 0
        for v in ctx.verdicts.values():
            if v.is_cheat or (include_watch and v.hits):
                self._alerts.append(Alert(v.suspicion, v.cn, v.name, v.category))
                added += 1
        self._alerts.sort(reverse=True)
        return added

    def __len__(self) -> int:
        return len(self._alerts)

    def __iter__(self):
        return iter(self._alerts)


def triage_match(
    events: list[dict[str, Any]],
    analyst: Analyst | None = None,
    match_id: str = "match",
    include_watch: bool = False,
) -> list[CaseReport]:
    """Run the full pipeline on one match: detect -> queue -> investigate."""
    analyst = analyst or HeuristicAnalyst()
    ctx = MatchContext.from_events(events, match_id=match_id)
    queue = AlertQueue()
    queue.ingest(ctx, include_watch=include_watch)
    return [analyst.investigate(ctx, alert.cn) for alert in queue]
