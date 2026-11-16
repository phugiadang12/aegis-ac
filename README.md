# Aegis AC

**Server-side behavioural anti-cheat with an AI SOC analyst.**

Red-team cheats against an open-source FPS (AssaultCube), ML-based detection,
honeypot entities, LLM-driven case investigation and replay-based evidence review.

> All cheat code in `redteam/` is for use **only** against a private, local
> AssaultCube server for research. Never run it on public servers or commercial games.

## Architecture

```
 AssaultCube server (patched)          Aegis AC
 ┌──────────────────────────┐   UDP   ┌─────────────┐   ┌─────────────┐
 │ player pos / aim / shots │ ──────▶ │  collector  │──▶│  detection  │
 │ honeypot "ghost" players │  JSONL  │  (FastAPI)  │   │ rules + ML  │
 └──────────────────────────┘         └─────────────┘   └──────┬──────┘
          ▲                                                    │ alerts
          │ kick / ban                                         ▼
 ┌────────┴────────┐     approve      ┌─────────────┐   ┌─────────────┐
 │   ban waves     │ ◀─────────────── │  dashboard  │◀──│ SOC agent   │
 └─────────────────┘                  │ + replays   │   │   (LLM)     │
                                      └─────────────┘   └─────────────┘
```

## Layout

| Folder | What lives there |
|---|---|
| `server-patch/` | Telemetry hook patch for the AssaultCube server (C++) |
| `collector/` | Ingests telemetry, stores events and player sessions (Python) |
| `detection/` | Rule-based + ML cheat detection, honeypot logic |
| `soc-agent/` | LLM analyst that investigates alerts and writes case reports |
| `dashboard/` | Live alerts, risk scores, replay viewer, ban approval (TypeScript) |
| `redteam/` | Research cheats: aimbot, humanised aimbot, triggerbot |
| `docs/` | Roadmap, design notes, write-ups |

See [docs/ROADMAP.md](docs/ROADMAP.md) for the build plan.

## Quick start (Windows)

```powershell
python -m venv $env:USERPROFILE\.venvs\aegis-ac
& $env:USERPROFILE\.venvs\aegis-ac\Scripts\Activate.ps1
pip install -e "collector[dev]"

# terminal 1 — collector (HTTP :8000, telemetry UDP :28800)
cd collector
uvicorn aegis_collector.app:create_app --factory --port 8000

# terminal 2 — stream a simulated 8-player match
python -m aegis_collector.sim --players 8 --seconds 60
```

Then open http://127.0.0.1:8000/docs to browse the API, or connect to
`ws://127.0.0.1:8000/ws/live` for the live event feed.

| Endpoint | Purpose |
|---|---|
| `GET /health` | accepted / rejected / stored counts |
| `GET /events?type=&match_id=&actor=&limit=` | recent events, newest first |
| `GET /matches` | matches seen so far |
| `GET /matches/{id}/players` | roster and online status |
| `POST /ingest` | JSON array of events |
| `WS /ws/live` | live event stream |

Run the tests with `pytest` inside `collector/`.
