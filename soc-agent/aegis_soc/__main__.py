"""Demo: generate a match, detect cheaters, and have the SOC analyst write up
each alert as a case report.

    python -m aegis_soc --profile esp
    python -m aegis_soc --profile aimbot --cheaters 2

By default it runs the deterministic analyst (no API key needed). With
ANTHROPIC_API_KEY set it uses the LLM agent; pass --no-llm to force the
deterministic one.
"""

import argparse

from aegis_collector.sim_cheat import Cheat, simulate_mixed

from .analyst import HeuristicAnalyst, build_analyst
from .triage import triage_match


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=[c.value for c in Cheat if c is not Cheat.LEGIT],
                    default="esp")
    ap.add_argument("--legit", type=int, default=6)
    ap.add_argument("--cheaters", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=45)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-llm", action="store_true", help="force deterministic analyst")
    args = ap.parse_args()

    ticks, labels = simulate_mixed(
        n_legit=args.legit, n_cheaters=args.cheaters,
        profile=Cheat(args.profile), seconds=args.seconds, seed=args.seed,
    )
    events = [ev for tick in ticks for ev in tick]

    analyst = HeuristicAnalyst() if args.no_llm else build_analyst()
    backend = type(analyst).__name__
    print(f"Analyst backend: {backend}\n")

    reports = triage_match(events, analyst=analyst, match_id=f"{args.profile}-demo")
    if not reports:
        print("No alerts — the detector flagged nobody in this match.")
        return
    for report in reports:
        truth = labels.get(report.cn, "?")
        print(report.render())
        print(f"(ground truth for cn {report.cn}: {truth})\n")


if __name__ == "__main__":
    main()
