"""The SOC analyst: turns a detector alert into a reviewed case report.

Two interchangeable backends:

* ``HeuristicAnalyst`` - deterministic, offline, no API key. It runs the same
  investigation tools an agent would and composes a report from the findings.
  This is what the tests and the default demo use, so the whole pipeline is
  reproducible with zero external dependencies.

* ``LLMAnalyst`` - a real tool-using agent (Anthropic SDK). It is handed the
  investigation tools and decides which evidence to gather, then emits the case
  report as a validated structured output. This is the Phase 4 headline; it is
  only imported/instantiated when the ``anthropic`` package and an API key are
  present.

``build_analyst()`` picks the LLM backend when it can and falls back to the
heuristic one otherwise, so callers never have to care which is running.
"""

import os
from typing import Protocol

from .evidence import Investigation, MatchContext
from .report import TAXONOMY, CaseReport

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """\
You are a security operations analyst on a game anti-cheat team. A behavioural \
detector has flagged a player in a match and opened an alert. Your job is to \
investigate the alert using the tools provided and file a case report that a \
human moderator will review before any action is taken.

You never ban a player yourself - you recommend a disposition and a human \
approves it. Be rigorous and fair: flagged players are sometimes just skilled, \
and a false ban is worse than a missed cheat here.

Cheat taxonomy to classify into:
{taxonomy}

How to work:
1. Pull the suspect's overview to see the detector's rule hits.
2. Compare them to the clean cohort with the baseline tool - a z-score far \
above the lobby's normal players is strong evidence; a value merely high is not.
3. Pull cheat_profile: it ranks likely cheat types and says whether anything \
seen is impossible for a human ("cheat_like") or only unusually strong \
("skill_or_cheat").
4. Gather the specific evidence for the suspected cheat: turn_timeline for \
aimbot snaps, aim_precision for lock-on / triggerbot reaction / silent-aim hits, \
honeypot for ESP/wallhack (shots at the phantom entity that no legitimate client \
can see are near-conclusive).
5. Weigh it and file one case report. Fill likely_types, a skill_check that \
names what rules skill out (or says nothing does), and a review_focus checklist \
for the human. Never recommend ban or shadow on "skill_or_cheat" evidence alone: \
very good players exist, so that is "monitor" plus a replay review.

Dispositions: "ban" (near-certain), "shadow" (confident - queue for a delayed \
ban wave so cheat authors can't correlate detection), "monitor" (suspicious but \
not conclusive), "clear" (the flag doesn't hold up)."""


class Analyst(Protocol):
    def investigate(self, ctx: MatchContext, cn: int) -> CaseReport: ...


# --------------------------------------------------------------------------
# Deterministic backend
# --------------------------------------------------------------------------
def _disposition(category: str, confidence: float) -> str:
    if confidence < 0.6:
        return "clear"
    if category == "aim_assistance":
        return "monitor"
    if confidence >= 0.92:
        return "ban"
    if confidence >= 0.8:
        return "shadow"
    return "monitor"


class HeuristicAnalyst:
    """Composes a case report from the investigation tools, no LLM involved."""

    def investigate(self, ctx: MatchContext, cn: int) -> CaseReport:
        inv = Investigation(ctx)
        ov = inv.overview(cn)
        base = inv.baseline(cn)
        hp = inv.honeypot(cn)
        turns = inv.turn_timeline(cn)
        profile = inv.cheat_profile(cn)

        verdict = ctx.verdicts[cn]
        category = verdict.category or "inconclusive"
        confidence = verdict.suspicion
        disposition = _disposition(category, confidence)
        if profile["label"] == "skill_or_cheat":
            disposition = "monitor"          # soft evidence: never ban, never clear blindly

        evidence: list[str] = [h["reason"] for h in ov["detector"]["rule_hits"]]
        if "comparisons" in base:
            worst = max(
                (c for c in base["comparisons"] if c["z_score"] != "inf"),
                key=lambda c: c["z_score"], default=None,
            )
            inf = [c for c in base["comparisons"] if c["z_score"] == "inf"]
            if inf:
                c = inf[0]
                evidence.append(
                    f"{c['metric']} of {c['suspect']} vs a clean-cohort max of "
                    f"{c['cohort_max']} - off the scale for this lobby")
            elif worst is not None and worst["z_score"] >= 2:
                evidence.append(
                    f"{worst['metric']} is {worst['z_score']} standard deviations "
                    f"above the clean cohort ({worst['suspect']} vs mean "
                    f"{worst['cohort_mean']})")
        if hp.get("blind_shots_at_phantom"):
            evidence.append(
                f"{hp['blind_shots_at_phantom']} shots at the phantom entity with "
                f"no real enemy on the aim line - impossible without a wallhack")
        if turns["sharpest_turns"] and category in ("aimbot", "humanised_aimbot"):
            fastest = turns["sharpest_turns"][0]
            evidence.append(
                f"peak view snap of {fastest['deg_per_s']} deg/s at t={fastest['ts']}ms")

        summary, recommendation = _narrative(category, confidence, disposition, ov)
        human = profile["human_signals"]
        skill_check = profile["explanation"]
        if profile["label"] == "skill_or_cheat" and human:
            skill_check += " Human-looking signals: " + "; ".join(human) + "."
        return CaseReport(
            cn=cn, name=ov["name"], category=category,
            confidence=round(confidence, 2), disposition=disposition,
            title=f"{category.replace('_', ' ')} - {ov['name']}",
            summary=summary, evidence=evidence or ["detector flag with no detail"],
            recommendation=recommendation,
            likely_types=[t["type"] for t in profile["likely_types"]],
            skill_check=skill_check,
            review_focus=profile["review_focus"],
        )


def _narrative(category: str, confidence: float, disposition: str, ov: dict):
    name = ov["name"]
    stats = ov["stats"]
    desc = TAXONOMY.get(category, "Unrecognised pattern.")
    summary = (
        f"{name} was flagged for {category.replace('_', ' ')}. {desc} "
        f"They landed {stats['hit_rate']*100:.0f}% of {stats['shots']} shots "
        f"with a peak turn rate of {stats['max_turn_rate']:.0f} deg/s across "
        f"{stats['kills']} kills. The pattern is {'well' if confidence >= 0.9 else 'partly'} "
        f"outside what the other players in the match produced."
    )
    actions = {
        "ban": "Approve a ban: the evidence is conclusive.",
        "shadow": "Queue for the next ban wave rather than banning now, so the "
                  "cheat author cannot tell which match exposed them.",
        "monitor": "Do not action yet - keep the player under watch and "
                   "re-evaluate across more matches.",
        "clear": "Dismiss the alert; the flag does not hold up.",
    }
    return summary, actions[disposition]


# --------------------------------------------------------------------------
# LLM backend (real tool-using agent)
# --------------------------------------------------------------------------
class LLMAnalyst:
    """A tool-using agent that investigates the alert with Claude, then files
    the case report as a validated structured output.

    Kept import-light: ``anthropic`` is imported lazily so the package works
    without it. The investigation tools are the exact same functions the
    heuristic backend calls - the model just decides which to use and how to
    weigh them.
    """

    def __init__(self, model: str = MODEL, max_iterations: int = 8, client=None):
        import anthropic  # noqa: F401  (fail fast if the SDK is missing)
        self.model = model
        self.max_iterations = max_iterations
        self._anthropic = anthropic
        self._client = client or anthropic.Anthropic()

    def _tools(self, inv: Investigation):
        """Expose the investigation methods as strict tool definitions + a
        dispatch table. Hand-written schemas keep us off the beta tool-runner
        decorator and let the final report use structured outputs."""
        defs = [
            ("roster", "List all players with the detector's suspicion score.", {}),
            ("overview", "Full stats and detector rule hits for one player.",
             {"cn": {"type": "integer"}}),
            ("baseline", "Z-score the player against the match's unflagged players.",
             {"cn": {"type": "integer"}}),
            ("turn_timeline", "The sharpest single-tick view snaps for a player.",
             {"cn": {"type": "integer"}}),
            ("honeypot", "Shots the player aimed at the hidden phantom entity.",
             {"cn": {"type": "integer"}}),
            ("aim_precision", "Lock-on error, reaction time and silent-aim hits, with sample sizes.",
             {"cn": {"type": "integer"}}),
            ("cheat_profile", "Ranked likely cheat types, skill check and review checklist.",
             {"cn": {"type": "integer"}}),
        ]
        tools = []
        for name, desc, props in defs:
            tools.append({
                "name": name, "description": desc, "strict": True,
                "input_schema": {
                    "type": "object", "properties": props,
                    "required": list(props), "additionalProperties": False,
                },
            })
        dispatch = {
            "roster": lambda **_: inv.roster(),
            "overview": lambda cn: inv.overview(cn),
            "baseline": lambda cn: inv.baseline(cn),
            "turn_timeline": lambda cn: inv.turn_timeline(cn),
            "honeypot": lambda cn: inv.honeypot(cn),
            "aim_precision": lambda cn: inv.aim_precision(cn),
            "cheat_profile": lambda cn: inv.cheat_profile(cn),
        }
        return tools, dispatch

    def investigate(self, ctx: MatchContext, cn: int) -> CaseReport:
        import json

        inv = Investigation(ctx)
        tools, dispatch = self._tools(inv)
        verdict = ctx.verdicts[cn]
        system = SYSTEM_PROMPT.format(
            taxonomy="\n".join(f"- {k}: {v}" for k, v in TAXONOMY.items()))
        messages = [{
            "role": "user",
            "content": (
                f"Alert on match {ctx.match_id}: player cn={cn} ({verdict.name}) "
                f"flagged with suspicion {verdict.suspicion:.2f}, suspected "
                f"{verdict.category}. Investigate and file a case report."
            ),
        }]

        # Investigation loop - the agent drives which tools to call.
        for _ in range(self.max_iterations):
            resp = self._client.messages.create(
                model=self.model, max_tokens=16000,
                thinking={"type": "adaptive"},
                system=system, tools=tools, messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "tool_use":
                break
            results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = dispatch[block.name](**block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(out)})
                except Exception as exc:  # surface tool errors to the model
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"error: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})

        # Synthesis - force a schema-valid case report out of the findings.
        messages.append({
            "role": "user",
            "content": "File your case report now based on the evidence you gathered.",
        })
        parsed = self._client.messages.parse(
            model=self.model, max_tokens=16000,
            system=system, messages=messages, output_format=CaseReport,
        )
        report = parsed.parsed_output
        report.cn, report.name = cn, verdict.name  # trust the alert for identity
        return report


def build_analyst(prefer_llm: bool = True) -> Analyst:
    """Return the LLM analyst when the SDK and an API key are available,
    otherwise the deterministic one."""
    if prefer_llm and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return LLMAnalyst()
        except Exception:
            pass
    return HeuristicAnalyst()
