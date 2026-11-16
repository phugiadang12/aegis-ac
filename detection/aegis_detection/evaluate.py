"""Score the detector against the simulator's ground-truth labels.

Runs many mixed matches per cheat profile, flags players, and compares to the
known labels to produce a confusion matrix and detection rate per profile.
This is the number that goes on the CV: "catches X% of aimbots at a Y% false
positive rate on Z simulated matches."

    python -m aegis_detection.evaluate --matches 20
"""

import argparse
from collections import defaultdict
from dataclasses import dataclass

from aegis_collector.sim_cheat import Cheat, simulate_mixed

from .features import extract_features
from .rules import judge_all


@dataclass
class Tally:
    tp: int = 0  # cheater, flagged
    fp: int = 0  # legit, flagged
    tn: int = 0  # legit, not flagged
    fn: int = 0  # cheater, missed

    @property
    def detection_rate(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def fp_rate(self) -> float:
        d = self.fp + self.tn
        return self.fp / d if d else 0.0


def evaluate(matches: int = 20, seconds: float = 45, legit: int = 6,
             cheaters: int = 2, base_seed: int = 1000) -> dict[str, Tally]:
    profiles = [c for c in Cheat if c is not Cheat.LEGIT]
    per_profile: dict[str, Tally] = defaultdict(Tally)
    overall = Tally()

    for profile in profiles:
        for m in range(matches):
            ticks, labels = simulate_mixed(
                n_legit=legit, n_cheaters=cheaters, profile=profile,
                seconds=seconds, seed=base_seed + m,
            )
            events = [ev for tick in ticks for ev in tick]
            verdicts = {v.cn: v for v in judge_all(extract_features(events))}

            for cn, label in labels.items():
                is_cheater = label != Cheat.LEGIT.value
                flagged = verdicts[cn].is_cheat if cn in verdicts else False
                t = per_profile[profile.value]
                for bucket in (t, overall):
                    if is_cheater and flagged:
                        bucket.tp += 1
                    elif is_cheater and not flagged:
                        bucket.fn += 1
                    elif not is_cheater and flagged:
                        bucket.fp += 1
                    else:
                        bucket.tn += 1

    per_profile["OVERALL"] = overall
    return per_profile


def _print(results: dict[str, Tally]) -> None:
    print(f"{'profile':<18}{'detect':>8}{'precision':>11}{'FP rate':>9}"
          f"{'TP':>5}{'FN':>4}{'FP':>4}{'TN':>5}")
    print("-" * 64)
    for name, t in results.items():
        print(f"{name:<18}{t.detection_rate*100:>7.0f}%{t.precision*100:>10.0f}%"
              f"{t.fp_rate*100:>8.0f}%{t.tp:>5}{t.fn:>4}{t.fp:>4}{t.tn:>5}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matches", type=int, default=20, help="matches per profile")
    ap.add_argument("--seconds", type=float, default=45)
    args = ap.parse_args()
    _print(evaluate(matches=args.matches, seconds=args.seconds))


if __name__ == "__main__":
    main()
