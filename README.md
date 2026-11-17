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
| `detection/` | Feature extraction, rule-based cheat detection, honeypot logic, scoring |
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

Run the tests with `pytest` from the repo root (covers both packages).

## Detection

```powershell
pip install -e "detection[dev]"
python -m aegis_detection.evaluate --matches 20   # score vs ground truth
```

The detector turns telemetry into per-player features and explainable verdicts:

| Feature | Cheat tell |
|---|---|
| `max_turn_rate` | aimbot snap (completes inside one tick) |
| `p95_turn_rate` + `hit_rate` | humanised aimbot |
| `hit_rate` | triggerbot / aimbot (lands almost everything) |
| `honeypot_shots` | ESP / wallhack (aimed at a server-only phantom) |

Current result on synthetic matches — **100% detection, 99% precision** over 160
cheaters and 480 legit players. The ESP wallhacker aims like a human and evades
every aim-based rule, yet the moving honeypot phantom still exposes it. Every
flag carries a human-readable reason for the AI analyst to quote.

## AI SOC analyst

```powershell
pip install -e "soc-agent"            # add [llm] for the Claude-driven agent
python -m aegis_soc --profile esp     # investigate a match's alerts
```

Each detector flag opens an alert. The analyst investigates it with the same
tools a human would — a stats overview, a z-score against the match's unflagged
players, the sharpest view snaps, and the honeypot evidence — then files a case
report with a confidence, a disposition (ban / shadow / monitor / clear) and the
reasoning, for a human to approve. Nothing is auto-banned.

Set `ANTHROPIC_API_KEY` and a Claude agent drives the investigation (it chooses
which tools to call via the Anthropic SDK, then emits the report as a validated
structured output). Without a key it runs a deterministic backend that produces
the same report shape, so the whole pipeline is reproducible offline.

```
CASE: esp - p07
Player      : p07 (cn 7)      Category: esp      Confidence: 95%      BAN
Evidence:
  - aimed at the phantom entity 8 times - only a wallhack can see it
  - shots at phantom entity is 16.3 standard deviations above the clean cohort
  - 8 shots at the phantom with no real enemy on the aim line
Recommendation: Approve a ban: the evidence is conclusive.
```
