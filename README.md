# Aegis AC

**A server-side anti-cheat for a multiplayer FPS, with an AI SOC analyst.**

![tests](https://img.shields.io/badge/tests-91%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.12-blue)
![frontend](https://img.shields.io/badge/dashboard-TypeScript%20%2B%20React-3178c6)
![model](https://img.shields.io/badge/AI-Claude%20(Anthropic%20SDK)-8a63d2)
![license](https://img.shields.io/badge/license-MIT-green)

Aegis AC watches what a game server already knows (where each player stands, where they
aim, what they shoot) and looks for behaviour a human can't produce. Each suspicious
player is checked by an AI analyst, which writes a case report. A human then decides,
and bans go out in delayed waves.

It runs in two modes:
- **Simulated matches.** No game needed. This is good for learning and for demos.
- **A real game.** Two people play on an AssaultCube server on your own computer, with
  an optional lab cheat client so there is a real cheater to catch.

![Aegis AC dashboard](docs/images/dashboard.jpg)

---

## How it works

```
  game server ──telemetry──▶ collector ──▶ detector ──alerts──▶ AI SOC analyst ──▶ dashboard
  (positions, aim, shots)    (validate,    (explainable          (investigates,      (human approves,
                              store)        rules + honeypot)     writes a case)      ban wave, Discord)
```

1. **Collect.** The game server sends one small JSON event per action over UDP. The
   collector checks each event against a strict schema and stores it in SQLite.
2. **Detect.** Every player in a match becomes a row of features (how fast they turn,
   how often they hit, whether they aim at a hidden "honeypot" target). Simple rules
   turn those features into a verdict, and every flag comes with a plain-English reason.
3. **Investigate.** An AI analyst (Claude, through the Anthropic SDK) looks at each flagged
   player with read-only tools, compares them to the clean players in the same match,
   and files a case report. Without an API key, a built-in rule-based analyst does the
   same job.
4. **Act.** The dashboard shows the alerts, the case reports and a 2D replay. A human
   approves, confirmed cheaters go into a delayed ban wave, and Discord gets a message.

| 2D replay: the suspect's aim (red) vs. other players | AI SOC case report |
|---|---|
| ![replay](docs/images/replay-viewer.jpg) | ![case report](docs/images/case-report.jpg) |

---

## Choose how you want to use it

| I want to… | Go to | Needs |
|---|---|---|
| See the whole pipeline without a game | [A. Simulated demo](#a-simulated-demo-no-game) | Python, Node |
| Run the anti-cheat / SOC on my own local game | [B. SOC on a real local game](#b-soc-on-a-real-local-game) | + VS 2022 Build Tools |
| Attack my own anti-cheat with a real cheat (LAN only) | [C. Red team (optional)](#c-red-team-optional) | + VS 2022 Build Tools |

**B and C are independent.** You can run the SOC without ever building the cheat. The
cheat client is a separate folder, so you can also use it to test a different
anti-cheat on your own LAN server.

### A. Simulated demo (no game)

```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -e collector -e detection -e soc-agent
pytest                                                   # 91 tests

python -m aegis_detection.evaluate --matches 20          # detector score vs ground truth
python -m aegis_soc --profile esp                        # AI analyst investigates a match

uvicorn aegis_soc.api:create_app --factory --port 8008   # terminal 1: analysis API
cd dashboard ; npm install ; npm run dev                 # terminal 2: http://localhost:5173
```

In the dashboard, **Inject cheater** creates a simulated cheater on demand, and you can
watch it get flagged, investigated and sent to Discord. To turn on the AI analyst
and Discord alerts, copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY` and
`DISCORD_WEBHOOK_URL`. Both are optional.

### B. SOC on a real local game

You need AssaultCube 1.3.0.2 (free) to play, and Visual Studio 2022 Build Tools to
build the patched server. Full details: [integrations/assaultcube](integrations/assaultcube).

```powershell
.\integrations\assaultcube\setup.ps1     # clone AssaultCube source, add the telemetry patch, build the server

# terminal 1: collector (listens for game telemetry on UDP 28800)
$env:AEGIS_DB = "data/lab.db"; uvicorn aegis_collector.app:create_app --factory --port 8000

# terminal 2: the patched game server (LAN only)
cd assaultcube ; .\bin_win32\ac_server_aegis.exe
```

Open AssaultCube, type `/connect localhost` in the console, and play. A second machine on
the same network can join too: see [docs/LAN-DEMO.md](docs/LAN-DEMO.md). Then scan the
matches:

```powershell
python -m aegis_detection.scan --db data/lab.db
```

```
ac-1794961039-2  (28879 events)
  clean   Cheater          suspicion 0.55  [skill_or_cheat]  likely: aimbot
           shots 23  hits 5  kills 1  peak turn 625 deg/s  lock 1.4 deg (10)  reaction 0 ms (0)  off-view hits 0
           ! crosshair was a median 1.4 deg from the enemy across 10 shots (provisional rule: no human baseline yet)
  clean   XP               suspicion 0.00  [low_data]  likely: -
```

Each player gets a **skill check** (`cheat_like`, `skill_or_cheat`, `clean`, `low_data`), the
**likely cheat type**, and (without `--brief`) a checklist of what to verify in the replay.
For full case reports from the SOC agent, run `python -m aegis_soc --db data/lab.db --watch`.
To test whether it catches cheaters rather than just good players, follow the
[pentest protocol](docs/PENTEST.md).

### C. Red team (optional)

A modified AssaultCube client with a wallhack (ESP) and an aimbot, plus an in-game menu
(**Insert**). **It refuses to connect to anything except your own computer or LAN.**
Full details: [redteam/assaultcube-client](redteam/assaultcube-client).

```powershell
.\redteam\assaultcube-client\setup.ps1
```

---

## Results

**On simulated matches:** 100% of 160 cheaters caught, with 1 false positive among 480
legit players. A wallhacker that aims like a human slips past every aim rule, but it
still gets caught by the honeypot: a hidden target only a wallhack can see.

**On a real game:** this is where it got interesting. Full write-up:
[docs/LAB.md](docs/LAB.md).

![turn rate in a real match](docs/images/lab/real-match-turn-rate.svg)

- **A:** during a real aimbot fight (23 shots, 5 hits, 1 kill) the cheater's turn speed
  stayed under the 900 °/s rule, so it was **not caught**. That limit was tuned on
  simulated data. On a real 30 Hz server, a smoothed aimbot looks slower.
- **B:** the player was flagged later, but the 932 °/s "snap" was a **respawn** (the
  position jumped and the view reset), not aiming. That is the right player for the
  wrong reason, and a human could trigger it too.

**What I changed after that:**
- **Respawns are ignored.** A position jump of more than 8 units in one tick is a
  teleport, not a turn (normal movement is under 1 unit per tick). The false flag is gone.
- **New measurements from real telemetry:** how close the crosshair is to the enemy at
  each shot (lock-on), time from crosshair-on-enemy to shot (triggerbot), and hits whose
  shot left far from the view (silent aim).
- **Skill or cheat?** The SOC agent now separates "impossible for a human" from "very
  good, but possible". The real aimbot rounds show a 1.4° median lock. That is
  suspicious, but I don't yet have real human numbers to compare, so the agent says
  `skill_or_cheat` → **monitor and review**, not ban. Calibrating that with real human
  rounds is the next step in [the pentest protocol](docs/PENTEST.md).

To me, finding problems like these is the point of testing on a real game instead of
only on my own simulator.

---

## Project layout

| Folder | What it is |
|---|---|
| `collector/` | Telemetry ingest (UDP + HTTP), strict schema, SQLite store, match simulators |
| `detection/` | Features, explainable rules, honeypot, cheat-type / skill check, evaluation, `scan` command |
| `soc-agent/` | AI SOC analyst, alert queue, ban waves, Discord notifier, dashboard API |
| `dashboard/` | TypeScript + React UI: alerts, case reports, 2D replay, ban waves |
| `integrations/assaultcube/` | **Blue team.** Telemetry patch for the real AssaultCube server |
| `redteam/assaultcube-client/` | **Red team, optional.** LAN-only lab cheat client |
| `docs/` | [Live lab report](docs/LAB.md), [pentest protocol](docs/PENTEST.md), [two-machine LAN demo](docs/LAN-DEMO.md), [roadmap](docs/ROADMAP.md) |

## Safety and ethics

This is a defensive project. The red-team client exists only so that the anti-cheat has a
real opponent in a lab:
- it is a source change to an **open-source** game;
- it **refuses to connect to non-LAN servers** (this is in code, not just a promise);
- it always shows an `AEGIS LAB BUILD` watermark;
- it is only built when you opt in.

There is no memory reading, no injection, no driver and no bypassing of any commercial
anti-cheat. It is never used on public servers or against real players.

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · SQLite · asyncio UDP · pytest · TypeScript · React ·
Vite · Claude (Anthropic SDK) · Discord webhooks · C++ (MSVC) for the game patches

## About me

I'm **Peter D** ([@phugiadang12](https://github.com/phugiadang12)), a recent graduate
looking for my first role in **game security / anti-cheat or SOC**. I built Aegis to learn
how these systems fit together end to end: collecting telemetry, detecting cheats with
rules I can explain, using an AI agent to help with investigations, and testing all of it
against a real game. The most useful lessons came from the parts that didn't work the
first time, and I've written those up honestly in [docs/LAB.md](docs/LAB.md).

## License

[MIT](LICENSE) © Peter D
