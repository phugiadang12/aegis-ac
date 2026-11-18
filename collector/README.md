# collector

Receives game telemetry, validates it and stores it.

- **UDP 28800**: JSON lines from the patched game server (fire-and-forget, so the game
  never waits on Aegis).
- **HTTP** (`uvicorn aegis_collector.app:create_app --factory --port 8000`): `POST /ingest`,
  `GET /health`, `/events`, `/matches`, `/matches/{id}/players`.
- **Schema** (`schema.py`): every event type is a strict Pydantic model. Malformed or
  unknown events are rejected and counted, never stored.
- **Store** (`store.py`): SQLite, one row per event. The path is set by `AEGIS_DB`.

`sim.py` and `sim_cheat.py` generate simulated matches for tests and the dashboard demo
([docs/SIMULATOR.md](../docs/SIMULATOR.md)).
