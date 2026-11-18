# soc-agent

The SOC side: investigate alerts, write cases, and handle enforcement.

| File | What it does |
|---|---|
| `evidence.py` | Read-only investigation tools: overview, baseline vs clean players, turn timeline, aim precision, cheat profile, honeypot |
| `analyst.py` | Claude analyst (tool use + structured case output) and a rule-based fallback with no API key |
| `report.py` | The case report: type, confidence, disposition, skill check, evidence, review checklist |
| `triage.py` | Alert queue, highest suspicion first; `--watch` adds borderline players |
| `enforcement.py` | Delayed ban waves: a human approves, the wave goes out later |
| `notify.py` | Discord webhook alerts (URL from `.env`) |
| `api.py` | HTTP API for the dashboard (`uvicorn aegis_soc.api:create_app --factory --port 8008`) |

```powershell
pip install -e "soc-agent[llm]"                          # with the Claude analyst
python -m aegis_soc --db data/lab.db --watch             # case reports for real matches
```

The analyst never bans on its own. It recommends `ban`, `shadow` (next ban wave),
`monitor` or `clear`, and a human approves.
