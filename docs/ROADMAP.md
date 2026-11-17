# Roadmap

Each phase ends with something you can demo.

## Phase 0 — Setup
- [x] Install Python 3.12, Git, Node.js LTS
- [x] Install Visual Studio 2022 Build Tools (C++ workload)
- [ ] Download AssaultCube, run a local game + local server
- [ ] `git init`, push to GitHub

## Phase 1 — Telemetry pipeline
- [x] Define telemetry event schema (position, aim, shots, hits, kills)
- [x] Collector service that ingests events and stores sessions
- [x] Simulator that generates fake legit players (test without the game)
- [x] Fix UDP packet loss under burst load (27% → 0% with 8 MB receive buffer)
- [ ] Patch AssaultCube server to stream real events to the collector
- **Demo:** live event feed from a real match

## Phase 2 — Red team (synthetic cheater telemetry)
We do NOT build a real cheat. We generate the telemetry *signatures* a cheat
would leave, labelled with ground truth, to train and score the detector.
No memory reading, no injection, no evading commercial/kernel anti-cheat.
- [x] Aimbot signature (instant snap, near-perfect accuracy)
- [x] Humanised aimbot (snap smoothed over 3-5 ticks + jitter)
- [x] Triggerbot (inhuman per-shot accuracy)
- [x] ESP / wallhack (tracks enemies with no line of sight; shoots honeypot ghost)
- [x] Mixed-match generator with per-player ground-truth labels
- **Demo:** kill counts already separate cheaters from legit players cleanly

## Phase 3 — Detection
- [x] Feature extractor from telemetry (turn rate, hit rate, headshot rate, honeypot)
- [x] Rule-based detector with explainable, human-readable reasons per flag
- [x] Honeypot phantom entity — server-tracked, moving; aiming at it = flag
- [x] Evaluation harness scoring vs ground-truth labels (confusion matrix)
- [ ] ML model on aim trajectories, scored against these same labelled matches
- [ ] Arms race: tune cheat to evade → retrain → chart the results
- **Result:** 100% detection, 99% precision over 160 cheaters + 480 legit players.
  The ESP wallhacker uses human aim (evades every aim-based rule) yet the
  honeypot still catches it.

## Phase 4 — AI SOC analyst
- [x] Alert queue (flagged players, highest suspicion first)
- [x] Investigation tools: overview, baseline (z-score vs clean cohort), turn
      timeline, honeypot evidence, lobby roster
- [x] LLM agent that calls those tools and files a structured case report
      (Claude via the Anthropic SDK), with a deterministic offline backend so
      the pipeline runs with no API key
- [x] Cheat taxonomy (aimbot, humanised aimbot, triggerbot, ESP, aim assist)
- [x] Case report with confidence + recommendation + disposition, human approves
- **Demo:** `python -m aegis_soc --profile esp` → a reviewed case card per alert

## Phase 5 — Dashboard & enforcement
- [x] Analysis API (FastAPI) composing detection + SOC + replay + ban waves
- [x] TypeScript + React dashboard: live alert queue with player risk scores
- [x] Case panel — the SOC analyst's report per alert, with evidence
- [x] 2D replay viewer (canvas): suspect's crosshair path vs. normal players,
      with the honeypot phantom drawn in
- [x] Delayed ban waves — queue confirmed cheaters, release together; pluggable
      kick executor (logs now, ready to wire to the AssaultCube server)
- [ ] Record the 2-minute end-to-end demo video for the README
- **Demo:** `uvicorn aegis_soc.api:create_app --factory --port 8008` + `npm run dev`
