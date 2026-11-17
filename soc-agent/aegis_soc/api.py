"""Analysis API for the dashboard.

Composes the whole stack behind an HTTP surface the TypeScript dashboard
consumes: detector alerts with risk scores, SOC case reports, 2D replay data,
and the delayed ban-wave queue.

For the demo it seeds itself with a spread of simulated matches on startup, so
the dashboard has something to show with a single `uvicorn` command and no game
server wired up yet. Each match is detected and (lazily) investigated once and
cached.

    uvicorn aegis_soc.api:create_app --factory --port 8008
"""

from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aegis_collector.sim import MAP_SIZE
from aegis_collector.sim_cheat import Cheat, simulate_mixed

from .analyst import Analyst, HeuristicAnalyst, build_analyst
from .enforcement import BanWave
from .evidence import MatchContext
from .notify import Notifier
from .report import CaseReport
from .triage import AlertQueue

# The matches the demo seeds on startup: (match_id, profile, n_cheaters, seed).
SEED_MATCHES = [
    ("scrim-01-esp", Cheat.ESP, 2, 5),
    ("scrim-02-aimbot", Cheat.AIMBOT, 1, 11),
    ("scrim-03-triggerbot", Cheat.TRIGGERBOT, 1, 23),
    ("scrim-04-humanised", Cheat.HUMANISED, 2, 31),
    ("scrim-05-clean", Cheat.LEGIT, 0, 40),
]


@dataclass
class MatchData:
    match_id: str
    profile: str
    events: list[dict[str, Any]]
    ctx: MatchContext
    labels: dict[int, str]
    reports: dict[int, CaseReport] = field(default_factory=dict)


class AnalysisService:
    def __init__(self, analyst: Analyst | None = None,
                 ban_delay_seconds: float = 3600.0,
                 notifier: Notifier | None = None) -> None:
        self.analyst: Analyst = analyst or HeuristicAnalyst()
        self.matches: dict[str, MatchData] = {}
        self.banwave = BanWave(delay_seconds=ban_delay_seconds)
        self.notifier = notifier or Notifier()
        self.notifications: list[dict[str, Any]] = []

    def seed(self) -> None:
        for match_id, profile, n_cheat, seed in SEED_MATCHES:
            ticks, labels = simulate_mixed(
                n_legit=6, n_cheaters=n_cheat, profile=profile,
                seconds=45, seed=seed,
            )
            events = [ev for tick in ticks for ev in tick]
            ctx = MatchContext.from_events(events, match_id=match_id)
            self.matches[match_id] = MatchData(
                match_id=match_id, profile=profile.value,
                events=events, ctx=ctx, labels=labels)

    # --- queries ----------------------------------------------------------
    def _match(self, match_id: str) -> MatchData:
        md = self.matches.get(match_id)
        if md is None:
            raise HTTPException(404, f"no match {match_id}")
        return md

    def match_summaries(self) -> list[dict[str, Any]]:
        out = []
        for md in self.matches.values():
            flagged = sum(v.is_cheat for v in md.ctx.verdicts.values())
            out.append({
                "match_id": md.match_id, "profile": md.profile,
                "players": len(md.ctx.verdicts), "flagged": flagged,
                "duration_ms": max((e["ts"] for e in md.events), default=0),
            })
        return out

    def alerts(self) -> list[dict[str, Any]]:
        alerts = []
        for md in self.matches.values():
            q = AlertQueue()
            q.ingest(md.ctx)
            for a in q:
                alerts.append({
                    "match_id": md.match_id, "cn": a.cn, "name": a.name,
                    "suspicion": round(a.suspicion, 3), "category": a.category,
                    "priority": a.priority,
                    "queued_for_ban": (md.match_id, a.cn) in {
                        (r.match_id, r.cn) for r in self.banwave.queued
                    },
                })
        alerts.sort(key=lambda a: a["suspicion"], reverse=True)
        return alerts

    def case(self, match_id: str, cn: int) -> CaseReport:
        md = self._match(match_id)
        if cn not in md.ctx.verdicts:
            raise HTTPException(404, f"no player cn={cn} in {match_id}")
        if cn not in md.reports:
            md.reports[cn] = self.analyst.investigate(md.ctx, cn)
        return md.reports[cn]

    def replay(self, match_id: str) -> dict[str, Any]:
        md = self._match(match_id)
        players = {
            v.cn: {"cn": v.cn, "name": v.name, "flagged": v.is_cheat,
                   "category": v.category, "suspicion": round(v.suspicion, 3)}
            for v in md.ctx.verdicts.values()
        }
        trajectories: dict[int, list[list[float]]] = {cn: [] for cn in players}
        shots: list[list[float]] = []
        honeypot: list[list[float]] = []
        for e in md.events:
            t = e["type"]
            if t == "tick" and e["cn"] in trajectories:
                trajectories[e["cn"]].append([
                    round(e["ts"], 0), round(e["pos"]["x"], 1),
                    round(e["pos"]["y"], 1), round(e["yaw"], 1),
                    1 if e.get("alive", True) else 0,
                ])
            elif t == "shot":
                shots.append([e["cn"], round(e["ts"], 0),
                              round(e["origin"]["x"], 1), round(e["origin"]["y"], 1),
                              round(e["target"]["x"], 1), round(e["target"]["y"], 1)])
            elif t == "honeypot":
                honeypot.append([round(e["ts"], 0),
                                 round(e["pos"]["x"], 1), round(e["pos"]["y"], 1)])
        return {
            "match_id": match_id, "map_size": MAP_SIZE,
            "duration_ms": max((e["ts"] for e in md.events), default=0),
            "players": list(players.values()),
            "trajectories": {str(cn): pts for cn, pts in trajectories.items()},
            "shots": shots, "honeypot": honeypot,
        }

    # --- enforcement ------------------------------------------------------
    def queue_ban(self, match_id: str, cn: int) -> dict[str, Any]:
        report = self.case(match_id, cn)
        if report.disposition == "clear":
            raise HTTPException(400, "player was cleared; nothing to enqueue")
        self.banwave.enqueue(match_id, cn, report.name,
                             report.category, report.confidence)
        self._dispatch(report, match_id)
        return self.banwave.snapshot()

    def _dispatch(self, report: CaseReport, match_id: str) -> list[dict[str, Any]]:
        """Fan a case out to the configured chat channels (Discord, …)."""
        results = [r.__dict__ for r in self.notifier.notify(report, match_id)]
        if results:
            self.notifications.append(
                {"match_id": match_id, "cn": report.cn, "results": results})
        return results

    def notify_test(self) -> dict[str, Any]:
        """Send the highest-suspicion case to every channel, to prove wiring."""
        if not self.notifier.channels:
            raise HTTPException(400, "no notification channels configured "
                                     "(set DISCORD_WEBHOOK_URL)")
        alerts = self.alerts()
        if not alerts:
            raise HTTPException(400, "no alerts to send")
        top = alerts[0]
        report = self.case(top["match_id"], top["cn"])
        return {"sent_to": self.notifier.configured,
                "results": self._dispatch(report, top["match_id"])}


def create_app(seed: bool = True, analyst: Analyst | None = None,
               notifier: Notifier | None = None) -> FastAPI:
    service = AnalysisService(analyst=analyst or build_analyst(),
                              notifier=notifier or Notifier.from_env())
    if seed:
        service.seed()

    app = FastAPI(title="Aegis AC analysis API")
    app.state.service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "matches": len(service.matches),
                "backend": type(service.analyst).__name__}

    @app.get("/api/matches")
    def matches():
        return service.match_summaries()

    @app.get("/api/alerts")
    def alerts():
        return service.alerts()

    @app.get("/api/matches/{match_id}/cases/{cn}")
    def case(match_id: str, cn: int):
        return service.case(match_id, cn).model_dump()

    @app.get("/api/matches/{match_id}/replay")
    def replay(match_id: str):
        return service.replay(match_id)

    @app.get("/api/banwave")
    def banwave():
        return service.banwave.snapshot()

    @app.post("/api/banwave/queue/{match_id}/{cn}")
    def queue_ban(match_id: str, cn: int):
        return service.queue_ban(match_id, cn)

    @app.post("/api/banwave/release")
    def release():
        released = service.banwave.release(force=True)
        return {"released": [r.as_dict() for r in released],
                **service.banwave.snapshot()}

    @app.get("/api/notify/status")
    def notify_status():
        return {"channels": service.notifier.configured,
                "sent": len(service.notifications)}

    @app.post("/api/notify/test")
    def notify_test():
        return service.notify_test()

    return app
