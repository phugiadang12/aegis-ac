# AssaultCube integration (blue team)

Adds live telemetry to the **open-source AssaultCube dedicated server**, so a real match on
your own PC streams into Aegis. This is all you need to run the anti-cheat / SOC on a real
game. You don't need the red-team cheat client.

## Quick setup

Requirements: Windows, Git, [Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
(C++ workload), and AssaultCube 1.3.0.2 installed to play.

```powershell
# from the aegis-ac folder
.\integrations\assaultcube\setup.ps1
```

The script clones AssaultCube's source into `.\assaultcube`, adds the patch and builds
`assaultcube\bin_win32\ac_server_aegis.exe`. The normal server isn't touched, and you
can safely run the script again.

## Run a match

```powershell
# 1. collector: receives telemetry on UDP 28800 and stores it
$env:AEGIS_DB = "data/lab.db"; uvicorn aegis_collector.app:create_app --factory --port 8000

# 2. patched game server (LAN only)
cd assaultcube ; .\bin_win32\ac_server_aegis.exe

# 3. play: open AssaultCube, press T and type  /connect localhost

# 4. check the results
python -m aegis_detection.scan --db data/lab.db
```

## What the patch does

One header file (`telemetry.h`) plus 11 lines in `server.cpp`. Each line is marked
`// Aegis AC`. The patch only **observes**: gameplay is unchanged.

| Game event | Aegis event |
|---|---|
| Player position + aim update | `player_join` (the first time a player is seen), then `tick`, about 30 per second |
| Weapon fired | `shot` (from → to) |
| Damage dealt | `damage` |
| Player killed | `kill` |
| Player leaves | `player_leave` |

- **One match per map.** The game clock restarts on each map, so every map gets its own
  `match_id` (`ac-<time>-<round>`).
- **Fail-safe.** Telemetry is fire-and-forget UDP, so if the collector is down the game
  keeps running normally.
- **LAN only.** Without a server key, the server never registers on the public server
  list.

## Files

| File | Purpose |
|---|---|
| `setup.ps1` | Clone source → apply patch → build |
| `telemetry.h` | Builds and sends the JSON events (depends only on enet + the C standard library) |
| `server.cpp.patch` | The 11 hook lines, made against AssaultCube commit `13f0d8e` (v1.3.0.2, protocol 1300) |
| `build.bat` | MSVC build of the server only |
