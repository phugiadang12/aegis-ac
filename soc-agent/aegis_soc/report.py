"""The case report - the analyst's deliverable for one alert.

A human reviewer reads this and approves or rejects the recommended action, so
it is deliberately explainable: a disposition, a confidence, the evidence that
supports it, and plain-language reasoning. It is a Pydantic model so the LLM
backend can emit it directly as a validated structured output.
"""

from typing import Literal

from pydantic import BaseModel, Field

# Disposition is intentionally conservative: the analyst never bans on its own,
# it recommends, and a human approves. "shadow" = keep playing but queue for a
# delayed ban wave (Phase 5) so cheat authors can't correlate detection.
Disposition = Literal["ban", "shadow", "monitor", "clear"]

# The cheat taxonomy the analyst classifies into.
TAXONOMY = {
    "aimbot": "Automated aim - pulls the crosshair onto enemies, as an instant snap or a smooth lock.",
    "humanised_aimbot": "Aim assist smoothed to look human, but still too accurate.",
    "triggerbot": "Auto-fires the instant the crosshair crosses an enemy.",
    "silent_aim": "Bullets go to the enemy while the view points elsewhere.",
    "esp": "Wallhack / ESP - knows enemy positions through walls.",
    "aim_assistance": "Soft aim help; weak signal, usually monitor not ban.",
    "inconclusive": "Flagged, but the evidence does not clearly fit one category.",
}


class CaseReport(BaseModel):
    """A SOC analyst's finding on a single flagged player."""

    cn: int = Field(description="The player's connection number (server id).")
    name: str = Field(description="The player's in-game name.")
    category: str = Field(
        description="Cheat category from the taxonomy, or 'inconclusive'.")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="How sure the analyst is that this is a cheater, 0-1.")
    disposition: Disposition = Field(
        description="Recommended action: ban, shadow (queue for a ban wave), "
                    "monitor, or clear.")
    title: str = Field(description="One-line headline for the case.")
    summary: str = Field(
        description="2-4 sentences: what the player did and why it is or isn't "
                    "cheating, in plain language.")
    evidence: list[str] = Field(
        description="Concrete facts pulled from the investigation tools, each a "
                    "short bullet with numbers.")
    recommendation: str = Field(
        description="What the human reviewer should do next and why.")
    likely_types: list[str] = Field(
        default_factory=list,
        description="Cheat types this could be, most likely first (taxonomy keys).")
    skill_check: str = Field(
        default="",
        description="Could a very skilled human produce this? Name the signals "
                    "that rule skill out, or say that none do.")
    review_focus: list[str] = Field(
        default_factory=list,
        description="What the human reviewer should check by hand in the replay.")

    def render(self) -> str:
        """Human-readable case card for the terminal / dashboard."""
        bar = "=" * 68
        bullets = "\n".join(f"  - {e}" for e in self.evidence)
        focus = "\n".join(f"  [ ] {x}" for x in self.review_focus)
        return (
            f"{bar}\n"
            f"CASE: {self.title}\n"
            f"{bar}\n"
            f"Player      : {self.name} (cn {self.cn})\n"
            f"Category    : {self.category}\n"
            f"Likely types: {', '.join(self.likely_types) or '-'}\n"
            f"Confidence  : {self.confidence*100:.0f}%\n"
            f"Disposition : {self.disposition.upper()}\n"
            f"\n{self.summary}\n"
            f"\nEvidence:\n{bullets}\n"
            f"\nSkill check:\n  {self.skill_check or '-'}\n"
            f"\nReview checklist:\n{focus or '  -'}\n"
            f"\nRecommendation:\n  {self.recommendation}\n"
            f"{bar}"
        )
