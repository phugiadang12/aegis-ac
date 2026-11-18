"""Have the SOC analyst write up each alert as a case report.

Real matches from the collector database (AssaultCube lab):

    python -m aegis_soc --db data/lab.db                      # every match
    python -m aegis_soc --db data/lab.db --match ac-1794961039-2 --watch

or a simulated match (no game needed):

    python -m aegis_soc --profile esp
    python -m aegis_soc --profile aimbot --cheaters 2

``--watch`` also investigates players who tripped a rule but stayed under the
flag threshold, e.g. a very good player or a careful cheat.

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
    ap.add_argument("--db", help="collector database with real matches")
    ap.add_argument("--match", help="only this match_id (with --db)")
    ap.add_argument("--watch", action="store_true",
                    help="also investigate players under the flag threshold")
    args = ap.parse_args()

    analyst = HeuristicAnalyst() if args.no_llm else build_analyst()
    print(f"Analyst backend: {type(analyst).__name__}\n")

    if args.db:
        from aegis_detection.scan import load_matches
        for mid, events in load_matches(args.db, args.match).items():
            reports = triage_match(events, analyst=analyst, match_id=mid,
                                   include_watch=args.watch)
            print(f"### {mid}: {len(reports) or 'no'} case(s)\n")
            for report in reports:
                print(report.render() + "\n")
        return

    ticks, labels = simulate_mixed(
        n_legit=args.legit, n_cheaters=args.cheaters,
        profile=Cheat(args.profile), seconds=args.seconds, seed=args.seed,
    )
    events = [ev for tick in ticks for ev in tick]
    reports = triage_match(events, analyst=analyst, match_id=f"{args.profile}-demo",
                           include_watch=args.watch)
    if not reports:
        print("No alerts - the detector flagged nobody in this match.")
        return
    for report in reports:
        truth = labels.get(report.cn, "?")
        print(report.render())
        print(f"(ground truth for cn {report.cn}: {truth})\n")


if __name__ == "__main__":
    main()
