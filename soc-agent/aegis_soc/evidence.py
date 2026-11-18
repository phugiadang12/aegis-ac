"""Investigation tools over a single match's telemetry.

This is the evidence layer the SOC analyst works from. Every method is
read-only, deterministic, and returns plain JSON-able data, so it can be
exposed verbatim as a tool to an LLM agent *or* called directly by the
deterministic analyst — the agent and the offline path see exactly the same
facts.

Nothing here uses the simulator's ground-truth labels. The "clean cohort" a
suspect is compared against is defined by the detector's own verdicts (players
it did not flag), which is what a real deployment has to work with.
"""

import math
import statistics
from dataclasses import dataclass
from typing import Any

from aegis_detection.classify import assess
from aegis_detection.features import TELEPORT_UNITS, PlayerFeatures, extract_features
from aegis_detection.rules import Verdict, judge_all

# Metrics the baseline tool compares a suspect against the clean cohort on.
# (attribute on PlayerFeatures, human label, higher_is_more_suspicious)
_BASELINE_METRICS = [
    ("hit_rate", "hit rate", True),
    ("headshot_rate", "headshot rate", True),
    ("max_turn_rate", "peak turn rate (deg/s)", True),
    ("p95_turn_rate", "sustained turn rate (deg/s)", True),
    ("honeypot_shots", "shots at phantom entity", True),
    ("off_view_hits", "hits that left far from the view", True),
    ("instant_reaction_rate", "share of one-tick reactions", True),
]


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


@dataclass
class MatchContext:
    """Everything the analyst can see about one match."""

    match_id: str
    events: list[dict[str, Any]]
    features: dict[int, PlayerFeatures]
    verdicts: dict[int, Verdict]

    @classmethod
    def from_events(cls, events: list[dict[str, Any]], match_id: str = "match") -> "MatchContext":
        feats = extract_features(events)
        verdicts = {v.cn: v for v in judge_all(feats)}
        return cls(match_id=match_id, events=events, features=feats, verdicts=verdicts)

    def clean_cohort(self, exclude: int) -> list[PlayerFeatures]:
        """Players the detector did NOT flag — the baseline of normal play."""
        return [
            self.features[cn]
            for cn, v in self.verdicts.items()
            if cn != exclude and not v.is_cheat and self.features[cn].shots > 0
        ]


class Investigation:
    """Bound to one suspect in one match; exposes the analyst's tool surface."""

    def __init__(self, ctx: MatchContext):
        self.ctx = ctx

    # --- tool: roster -----------------------------------------------------
    def roster(self) -> dict[str, Any]:
        """List every player in the match with the detector's suspicion score,
        so you can see the suspect in the context of the lobby."""
        return {
            "match_id": self.ctx.match_id,
            "players": [
                {
                    "cn": v.cn,
                    "name": v.name,
                    "suspicion": round(v.suspicion, 2),
                    "flagged": v.is_cheat,
                    "category": v.category,
                }
                for v in sorted(self.ctx.verdicts.values(),
                                key=lambda v: v.suspicion, reverse=True)
            ],
        }

    # --- tool: overview ---------------------------------------------------
    def overview(self, cn: int) -> dict[str, Any]:
        """Full performance profile for one player plus the detector's rule
        hits. The first thing to pull on any alert."""
        f = self.ctx.features.get(cn)
        if f is None:
            return {"error": f"no player with cn={cn} in this match"}
        v = self.ctx.verdicts[cn]
        return {
            "cn": cn,
            "name": f.name,
            "stats": f.as_dict(),
            "detector": {
                "suspicion": round(v.suspicion, 3),
                "flagged": v.is_cheat,
                "top_category": v.category,
                "rule_hits": [
                    {"rule": h.rule, "category": h.category,
                     "confidence": h.confidence, "reason": h.reason}
                    for h in v.hits
                ],
            },
        }

    # --- tool: baseline ---------------------------------------------------
    def baseline(self, cn: int) -> dict[str, Any]:
        """Compare the suspect to the match's unflagged players (the clean
        cohort) on every cheat-relevant metric, as a z-score. A z-score above
        ~3 means the value is far outside what normal players in this same
        lobby produced."""
        f = self.ctx.features.get(cn)
        if f is None:
            return {"error": f"no player with cn={cn} in this match"}
        cohort = self.ctx.clean_cohort(exclude=cn)
        if len(cohort) < 2:
            return {"error": "not enough clean players to form a baseline",
                    "cohort_size": len(cohort)}

        comparisons = []
        for attr, label, _ in _BASELINE_METRICS:
            suspect = float(getattr(f, attr))
            values = [float(getattr(c, attr)) for c in cohort]
            mean = statistics.fmean(values)
            sd = statistics.pstdev(values)
            z = (suspect - mean) / sd if sd > 1e-9 else (
                math.inf if suspect > mean else 0.0)
            comparisons.append({
                "metric": label,
                "suspect": round(suspect, 3),
                "cohort_mean": round(mean, 3),
                "cohort_max": round(max(values), 3),
                "z_score": (round(z, 1) if math.isfinite(z) else "inf"),
            })
        return {"cn": cn, "cohort_size": len(cohort), "comparisons": comparisons}

    # --- tool: turn timeline ---------------------------------------------
    def turn_timeline(self, cn: int, top: int = 5) -> dict[str, Any]:
        """The sharpest view-angle changes for a player, each as deg/s with a
        timestamp. Aimbot snaps show up here as single-tick turns an order of
        magnitude faster than a human flick."""
        ticks = sorted(
            ((e["ts"], e["yaw"], e["pos"]) for e in self.ctx.events
             if e["type"] == "tick" and e["cn"] == cn),
            key=lambda p: p[0],
        )
        spikes = []
        for (t0, y0, p0), (t1, y1, p1) in zip(ticks, ticks[1:]):
            dt = (t1 - t0) / 1000.0
            jump = math.dist((p0["x"], p0["y"], p0.get("z", 0.0)),
                             (p1["x"], p1["y"], p1.get("z", 0.0)))
            if jump > TELEPORT_UNITS:
                continue                      # respawn / teleport, not a turn
            if 0 < dt <= 0.1:
                spikes.append({"ts": round(t1, 1),
                               "deg_per_s": round(abs(_wrap180(y1 - y0)) / dt, 1)})
        spikes.sort(key=lambda s: s["deg_per_s"], reverse=True)
        return {"cn": cn, "sampled_ticks": len(ticks), "sharpest_turns": spikes[:top]}

    # --- tool: aim precision ---------------------------------------------
    def aim_precision(self, cn: int) -> dict[str, Any]:
        """How the player's crosshair relates to enemies and to their own shots:
        lock-on error at each shot (aimbot), reaction time from crosshair-on-enemy
        to first shot (triggerbot), and hits whose shot left far from the view
        (silent aim). Each number comes with its sample size - small samples are
        weak evidence."""
        f = self.ctx.features.get(cn)
        if f is None:
            return {"error": f"no player with cn={cn} in this match"}
        return {
            "cn": cn,
            "lock_error_median_deg": round(f.lock_error_median, 2),
            "lock_samples": f.lock_samples,
            "reaction_median_ms": round(f.reaction_median_ms, 1),
            "reaction_samples": f.reaction_samples,
            "instant_reaction_rate": round(f.instant_reaction_rate, 3),
            "shot_offset_median_deg": round(f.shot_offset_median, 2),
            "off_view_hits": f.off_view_hits,
            "respawn_teleports_ignored": f.teleports,
        }

    # --- tool: cheat profile ---------------------------------------------
    def cheat_profile(self, cn: int) -> dict[str, Any]:
        """The detector's cheat-type assessment: likely cheat types with their
        evidence, a skill check (cheat_like = something no human can do;
        skill_or_cheat = strong but humanly possible; clean; low_data), the
        signals that look human, and what a reviewer should check by hand."""
        f = self.ctx.features.get(cn)
        if f is None:
            return {"error": f"no player with cn={cn} in this match"}
        return assess(f, self.ctx.verdicts[cn]).as_dict()

    # --- tool: honeypot ---------------------------------------------------
    def honeypot(self, cn: int, limit: int = 8) -> dict[str, Any]:
        """Every shot this player aimed at the server's phantom (honeypot)
        entity — a target no legitimate client is ever told exists. Each entry
        notes whether a real enemy was also on the aim line; shots with none
        are the wallhack tell."""
        ghost = {e["ts"]: (e["pos"]["x"], e["pos"]["y"])
                 for e in self.ctx.events if e["type"] == "honeypot"}
        if not ghost:
            return {"cn": cn, "phantom_tracked": False, "shots_at_phantom": []}

        positions: dict[float, dict[int, tuple[float, float]]] = {}
        for e in self.ctx.events:
            if e["type"] == "tick":
                positions.setdefault(e["ts"], {})[e["cn"]] = (e["pos"]["x"], e["pos"]["y"])

        hits = []
        for e in self.ctx.events:
            if e["type"] != "shot" or e["cn"] != cn or e["ts"] not in ghost:
                continue
            ox, oy = e["origin"]["x"], e["origin"]["y"]
            aim = math.degrees(math.atan2(e["target"]["y"] - oy, e["target"]["x"] - ox))
            gx, gy = ghost[e["ts"]]
            off = abs(_wrap180(math.degrees(math.atan2(gy - oy, gx - ox)) - aim))
            if off > 6.0:
                continue
            enemy_near = any(
                abs(_wrap180(math.degrees(math.atan2(py - oy, px - ox)) - aim)) <= 6.0
                for other, (px, py) in positions.get(e["ts"], {}).items() if other != cn
            )
            hits.append({"ts": round(e["ts"], 1), "degrees_off_phantom": round(off, 1),
                         "real_enemy_on_line": enemy_near})
        blind = [h for h in hits if not h["real_enemy_on_line"]]
        return {
            "cn": cn,
            "phantom_tracked": True,
            "shots_at_phantom": len(hits),
            "blind_shots_at_phantom": len(blind),
            "sample": blind[:limit] or hits[:limit],
        }
