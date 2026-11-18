# detection

Turns one match's telemetry into a verdict per player.

| File | What it does |
|---|---|
| `features.py` | Measurements per player: turn speed (respawns skipped), accuracy, lock-on error, reaction time, off-view hits, honeypot shots |
| `rules.py` | Explainable rules: each flag has a confidence, a cheat type and a plain-English reason |
| `classify.py` | Likely cheat types, skill check (`cheat_like` / `skill_or_cheat` / `clean` / `low_data`), review checklist |
| `scan.py` | `python -m aegis_detection.scan --db data/lab.db`: run it all on a database |
| `mutate.py` | `python -m aegis_detection.mutate`: add a cheat's footprint to a real match ([docs/MUTATION.md](../docs/MUTATION.md)) |
| `evaluate.py` | Score against simulated ground truth ([docs/SIMULATOR.md](../docs/SIMULATOR.md)) |
