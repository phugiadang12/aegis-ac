"""Scan a collector database and print a verdict for every player in every match.

This is the quickest way to run Aegis on your own game: point the collector at a
database, play, then run

    python -m aegis_detection.scan --db data/lab.db
    python -m aegis_detection.scan --db data/lab.db --match ac-1794961039-2 --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter

from .features import extract_features
from .rules import judge_all


def load_matches(db_path: str, match_id: str | None = None) -> dict[str, list[dict]]:
    """Return {match_id: [event, ...]} in arrival order."""
    con = sqlite3.connect(db_path)
    try:
        sql = "SELECT match_id, payload FROM events"
        args: tuple = ()
        if match_id:
            sql += " WHERE match_id = ?"
            args = (match_id,)
        matches: dict[str, list[dict]] = {}
        for mid, payload in con.execute(sql + " ORDER BY id", args):
            matches.setdefault(mid, []).append(json.loads(payload))
        return matches
    finally:
        con.close()


def scan(db_path: str, match_id: str | None = None) -> list[dict]:
    """One result row per match: event counts plus each player's verdict and features."""
    results = []
    for mid, events in load_matches(db_path, match_id).items():
        feats = extract_features(events)
        players = []
        for v in judge_all(feats):
            f = feats[v.cn]
            players.append({
                **v.as_dict(),
                "shots": f.shots, "hits": f.hits, "kills": f.kills, "deaths": f.deaths,
                "max_turn_rate": round(f.max_turn_rate, 1),
                "p95_turn_rate": round(f.p95_turn_rate, 1),
            })
        results.append({"match_id": mid, "events": dict(Counter(e["type"] for e in events)),
                        "players": players})
    return results


def _print(results: list[dict]) -> None:
    if not results:
        print("no matches in this database yet")
        return
    for m in results:
        total = sum(m["events"].values())
        print(f"\n{m['match_id']}  ({total} events)")
        for p in m["players"]:
            mark = "FLAGGED" if p["is_cheat"] else "clean  "
            print(f"  {mark} {p['name']:<16} suspicion {p['suspicion']:.2f}  "
                  f"shots {p['shots']:>3}  hits {p['hits']:>3}  kills {p['kills']:>2}  "
                  f"peak turn {p['max_turn_rate']:>6.0f} deg/s")
            for r in p["reasons"]:
                print(f"           - {r}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Run the Aegis detector over a collector database.")
    ap.add_argument("--db", default="data/aegis.db", help="SQLite file the collector writes")
    ap.add_argument("--match", help="only this match_id")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    results = scan(args.db, args.match)
    print(json.dumps(results, indent=2)) if args.json else _print(results)


if __name__ == "__main__":
    main()
