"""The scan CLI reads a real collector database and judges every match in it."""

from aegis_collector.schema import EventAdapter
from aegis_collector.sim_cheat import Cheat, simulate_mixed
from aegis_collector.store import EventStore
from aegis_detection.scan import main, scan


def _db_with_aimbot_match(tmp_path):
    db = tmp_path / "lab.db"
    ticks, labels = simulate_mixed(n_legit=4, n_cheaters=1, profile=Cheat.AIMBOT,
                                   seconds=30, seed=7)
    store = EventStore(db)
    store.add_many([EventAdapter.validate_python(ev) for tick in ticks for ev in tick])
    return db, labels


def test_scan_flags_the_cheater_only(tmp_path):
    db, labels = _db_with_aimbot_match(tmp_path)
    [match] = scan(str(db))
    flagged = {p["cn"] for p in match["players"] if p["is_cheat"]}
    assert flagged == {cn for cn, lab in labels.items() if lab != "legit"}
    assert match["events"]["tick"] > 0


def test_scan_filters_by_match_and_prints(tmp_path, capsys):
    db, _ = _db_with_aimbot_match(tmp_path)
    assert scan(str(db), match_id="no-such-match") == []
    main(["--db", str(db)])
    out = capsys.readouterr().out
    assert "FLAGGED" in out and "clean" in out
