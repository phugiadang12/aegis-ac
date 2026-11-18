"""Rule-based detector.

Explainable on purpose: every flag comes with the feature that tripped it and a
human-readable reason, which is what the AI SOC analyst (Phase 4) and the replay
viewer (Phase 5) quote back. An ML model comes later and will be scored against
exactly these same labelled matches, so we can show it beats the rules.

Each rule reads a PlayerFeatures row and, if it fires, returns a Hit with a
confidence and the cheat category it points to. A player's overall suspicion is
the strongest single hit, nudged up when several independent rules agree.
"""

from dataclasses import dataclass, field

from .features import PlayerFeatures

# Minimum activity before a rate-based rule is trusted — protects players who
# barely fired from being flagged on noise.
MIN_SHOTS = 8
MIN_HITS = 6

# A human flick tops out a few hundred deg/s; an aimbot snap is an order of
# magnitude faster because it completes inside one server tick.
TURN_IMPOSSIBLE = 900.0   # deg/s -> near-certain aimbot
TURN_SUSTAINED = 500.0    # deg/s at p95 -> fast, suspicious if paired with accuracy

HIT_RATE_INHUMAN = 0.90   # lands almost everything -> triggerbot / aimbot
HIT_RATE_HIGH = 0.65      # strong, suspicious when paired with fast turning
HEADSHOT_SUSPICIOUS = 0.50
MIN_HONEYPOT_SHOTS = 3    # shots at the phantom entity -> ESP / wallhack

# Silent aim: hits whose shot left far from where the player was looking.
MIN_OFF_VIEW_HITS = 2
# Triggerbot: the first shot comes within one server tick of the crosshair
# reaching an enemy, most of the time. Human reaction is ~150-250 ms.
MIN_REACTIONS = 8          # with 5, 3 lucky fast shots were enough for a false flag
INSTANT_REACTION_SHARE = 0.60
# Lock-on: median distance (deg) between crosshair and enemy at the moment of
# each shot. PROVISIONAL: real aimbot rounds measured 1.4 and 2.2 deg; we have no
# real human baseline yet, so this rule alone stays below the flag threshold.
MIN_LOCK_SAMPLES = 8
LOCK_TIGHT_DEG = 2.5

CHEAT_THRESHOLD = 0.60    # overall suspicion at/above this -> flagged


@dataclass
class Hit:
    rule: str
    category: str
    confidence: float
    reason: str


@dataclass
class Verdict:
    cn: int
    name: str
    suspicion: float
    is_cheat: bool
    category: str | None
    hits: list[Hit] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "cn": self.cn, "name": self.name,
            "suspicion": round(self.suspicion, 3),
            "is_cheat": self.is_cheat, "category": self.category,
            "reasons": [h.reason for h in self.hits],
        }


def _rules(f: PlayerFeatures) -> list[Hit]:
    hits: list[Hit] = []

    if f.max_turn_rate > TURN_IMPOSSIBLE:
        hits.append(Hit(
            "impossible_turn", "aimbot", 0.96,
            f"view snapped at {f.max_turn_rate:.0f} deg/s "
            f"(human flicks stay well under {TURN_IMPOSSIBLE:.0f})",
        ))

    if f.shots >= MIN_SHOTS and f.hit_rate >= HIT_RATE_INHUMAN:
        hits.append(Hit(
            "inhuman_accuracy", "triggerbot", 0.90,
            f"landed {f.hit_rate*100:.0f}% of {f.shots} shots",
        ))

    if (f.shots >= MIN_SHOTS and f.hit_rate >= HIT_RATE_HIGH
            and f.p95_turn_rate > TURN_SUSTAINED):
        hits.append(Hit(
            "fast_and_accurate", "humanised_aimbot", 0.80,
            f"{f.hit_rate*100:.0f}% accuracy with sustained "
            f"{f.p95_turn_rate:.0f} deg/s turns",
        ))

    if f.honeypot_shots >= MIN_HONEYPOT_SHOTS:
        hits.append(Hit(
            "honeypot", "esp", 0.95,
            f"aimed at the phantom entity {f.honeypot_shots} times — "
            f"only a wallhack can see it",
        ))

    if f.off_view_hits >= MIN_OFF_VIEW_HITS:
        hits.append(Hit(
            "off_view_hits", "silent_aim", 0.93,
            f"{f.off_view_hits} hits landed with the shot leaving far from where "
            f"the player was looking (normal spread is a few degrees)",
        ))

    if (f.reaction_samples >= MIN_REACTIONS
            and f.instant_reaction_rate >= INSTANT_REACTION_SHARE):
        hits.append(Hit(
            "instant_reaction", "triggerbot", 0.85,
            f"fired within one tick of the crosshair reaching an enemy in "
            f"{f.instant_reaction_rate*100:.0f}% of {f.reaction_samples} engagements "
            f"(median {f.reaction_median_ms:.0f} ms; humans need ~150-250 ms)",
        ))

    if f.lock_samples >= MIN_LOCK_SAMPLES and f.lock_error_median <= LOCK_TIGHT_DEG:
        hits.append(Hit(
            "tight_lock", "aimbot", 0.55,
            f"crosshair was a median {f.lock_error_median:.1f} deg from the enemy "
            f"across {f.lock_samples} shots (provisional rule: no human baseline yet)",
        ))

    if f.hits >= MIN_HITS and f.headshot_rate >= HEADSHOT_SUSPICIOUS:
        hits.append(Hit(
            "high_headshot", "aim_assistance", 0.45,
            f"{f.headshot_rate*100:.0f}% of hits were headshots",
        ))

    return hits


def judge(f: PlayerFeatures) -> Verdict:
    hits = sorted(_rules(f), key=lambda h: h.confidence, reverse=True)
    if not hits:
        return Verdict(f.cn, f.name, 0.0, False, None, [])

    suspicion = hits[0].confidence
    # independent corroboration raises confidence, but never past 0.99
    if len(hits) > 1:
        suspicion = min(0.99, suspicion + 0.03 * (len(hits) - 1))

    return Verdict(
        cn=f.cn, name=f.name, suspicion=suspicion,
        is_cheat=suspicion >= CHEAT_THRESHOLD,
        category=hits[0].category, hits=hits,
    )


def judge_all(feats: dict[int, PlayerFeatures]) -> list[Verdict]:
    return sorted(
        (judge(f) for f in feats.values()),
        key=lambda v: v.suspicion, reverse=True,
    )
