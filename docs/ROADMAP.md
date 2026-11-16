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
- [ ] Rule-based detectors (snap angle, reaction time, headshot ratio)
- [ ] Honeypot ghost entities — aiming at an invisible player = flag
- [ ] ML model on aim trajectories, with explanations for each flag
- [ ] Arms race: tune cheat to evade → retrain → chart the results
- **Demo:** detection rate per cheat type

## Phase 4 — AI SOC analyst
- [ ] Alert queue
- [ ] LLM agent with tools: player history, baseline comparison, replay fetch
- [ ] Cheat taxonomy (aim assist, wallhack, speed, triggerbot)
- [ ] Case report with confidence + recommendation, human approves
- **Demo:** alert → AI case report in seconds

## Phase 5 — Dashboard & enforcement
- [ ] Live alerts and player risk scores
- [ ] 2D replay viewer: suspect's crosshair path vs. normal players
- [ ] Delayed ban waves → kick from the AssaultCube server
- **Demo:** the 2-minute end-to-end video for the README
