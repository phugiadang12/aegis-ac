"""Cheat-type assessment: which cheat does this look like, and could it just be skill?

The rules say *whether* a player is suspicious. A human reviewer also needs to
know *what to look at*. This module turns a player's features and rule hits into:

  * a ranked list of likely cheat types, each with the evidence behind it;
  * a skill check: "cheat-like" (something no human can do), "skill or cheat"
    (great results, but every timing signal is human), "clean" or "low data";
  * a review focus: what to check by hand in the replay for the top type.

Hard evidence (things skill cannot explain): a view snap faster than any human,
shots at the honeypot, hits that left far from the view, reactions inside one
server tick. Soft evidence (a very good player can also produce it): high
accuracy, many headshots, fast-and-accurate, a tight lock on enemies.
"""

from dataclasses import asdict, dataclass, field

from .features import PlayerFeatures
from .rules import LOCK_TIGHT_DEG, MIN_SHOTS, TURN_IMPOSSIBLE, Verdict

HARD_RULES = {"impossible_turn", "honeypot", "off_view_hits", "instant_reaction"}
HUMAN_REACTION_MS = 150.0

CHEAT_TYPES = {
    "aimbot": "Automated aim: pulls the crosshair onto enemies.",
    "humanised_aimbot": "Aimbot smoothed to look human, but still too accurate.",
    "triggerbot": "Fires automatically the instant the crosshair is on an enemy.",
    "silent_aim": "Bullets go to the enemy while the screen points elsewhere.",
    "esp": "Wallhack / ESP: knows where enemies are through walls.",
    "aim_assistance": "Weak aim help; low confidence on its own.",
}

REVIEW_FOCUS = {
    "aimbot": [
        "Replay each kill: does the crosshair jump onto the enemy and stop dead on them?",
        "Open the turn timeline around the kills and compare it with the clean players.",
        "Check whether the lock holds while the enemy strafes (humans trail behind).",
    ],
    "humanised_aimbot": [
        "Watch long fights: is tracking smooth with almost no overshoot or correction?",
        "Compare accuracy with the player's other matches - is this a sudden jump?",
    ],
    "triggerbot": [
        "Watch frames where the crosshair crosses an enemy: does the shot fire on that exact frame every time?",
        "Check if the player fires at enemies who only appear for a moment (humans miss those).",
    ],
    "silent_aim": [
        "Find the listed hits and check the screen: the crosshair should be clearly off the victim.",
        "Compare the shot direction with the view angle for those shots (normal spread is a few degrees).",
    ],
    "esp": [
        "Watch for pre-aiming at walls and corners before an enemy appears.",
        "Check honeypot shots: the phantom is invisible to normal clients.",
        "Look for the player turning toward enemies they cannot hear or see.",
    ],
    "aim_assistance": [
        "Collect more matches before deciding; this signal alone is weak.",
    ],
}


@dataclass
class TypeScore:
    type: str
    score: float
    description: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class Assessment:
    cn: int
    name: str
    label: str            # cheat_like | skill_or_cheat | clean | low_data
    explanation: str
    likely_types: list[TypeScore] = field(default_factory=list)
    cheat_signals: list[str] = field(default_factory=list)
    human_signals: list[str] = field(default_factory=list)
    review_focus: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def _human_signals(f: PlayerFeatures) -> list[str]:
    """Signals consistent with a real (possibly very good) human."""
    out = []
    if f.max_turn_rate and f.max_turn_rate <= TURN_IMPOSSIBLE:
        out.append(f"peak turn {f.max_turn_rate:.0f} deg/s is within human range")
    if f.reaction_samples >= 3 and HUMAN_REACTION_MS <= f.reaction_median_ms <= 1000:
        out.append(f"median reaction {f.reaction_median_ms:.0f} ms is human")
    if f.lock_samples >= 3 and f.lock_error_median > LOCK_TIGHT_DEG:
        out.append(f"crosshair a median {f.lock_error_median:.1f} deg off target: normal human error")
    if f.shots and f.off_view_hits == 0:
        out.append("every hit was aimed with the view (no silent-aim hits)")
    if f.honeypot_shots == 0:
        out.append("never aimed at the honeypot phantom")
    return out


def assess(f: PlayerFeatures, v: Verdict) -> Assessment:
    by_type: dict[str, TypeScore] = {}
    for h in v.hits:
        ts = by_type.setdefault(
            h.category, TypeScore(h.category, 0.0, CHEAT_TYPES.get(h.category, "")))
        ts.score = max(ts.score, h.confidence)
        ts.evidence.append(h.reason)
    types = sorted(by_type.values(), key=lambda t: t.score, reverse=True)

    hard = [h.reason for h in v.hits if h.rule in HARD_RULES]
    soft = [h.reason for h in v.hits if h.rule not in HARD_RULES]
    human = _human_signals(f)
    focus = REVIEW_FOCUS.get(types[0].type, []) if types else []

    if hard:
        label = "cheat_like"
        explanation = ("At least one signal cannot be produced by skill: "
                       + hard[0] + ".")
    elif soft:
        label = "skill_or_cheat"
        explanation = ("Some signals are unusual, but none is impossible for a "
                       "human. Treat as 'very good player OR careful cheat' and "
                       "check the replay before any action.")
        focus = focus + ["Compare with the player's history: a steady high level "
                         "suggests skill, a sudden jump suggests a cheat."]
    elif f.shots < MIN_SHOTS:
        label = "low_data"
        explanation = (f"Only {f.shots} shots - not enough activity to judge either way.")
    else:
        label = "clean"
        explanation = "No cheat signals; all measured timings look human."

    return Assessment(
        cn=f.cn, name=f.name, label=label, explanation=explanation,
        likely_types=types, cheat_signals=hard + soft, human_signals=human,
        review_focus=focus,
    )
