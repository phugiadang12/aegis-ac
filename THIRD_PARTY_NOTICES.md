# Third-party notices

Aegis AC's own code is released under the [MIT licence](LICENSE). This file lists the
third-party software it works with, and the one part of this repository that is **not**
under MIT.

## AssaultCube (not included; patches are under AssaultCube's licence)

Aegis AC is tested on [AssaultCube](https://assault.cubers.net/) 1.3.0.2, an open-source
FPS by the AssaultCube team, based on the Cube engine by Wouter van Oortmerssen.

- **No AssaultCube code, binaries or media are included in this repository.** The setup
  scripts download the official source from GitHub at commit `13f0d8e`, and the build
  output stays in the git-ignored `assaultcube/` folder.
- **These two files modify AssaultCube source code and are distributed under
  AssaultCube's licence, not MIT:**
  - `integrations/assaultcube/server.cpp.patch`
  - `redteam/assaultcube-client/client.patch`

  AssaultCube's source is under a zlib-like licence with an extra Cube clause: the source
  may not be relicensed under a different licence. Altered versions must be plainly
  marked: every changed line is tagged `// Aegis AC`, and the builds use different names
  (`ac_server_aegis.exe`, `ac_client_lab.exe`). Full terms:
  <https://assault.cubers.net/docs/license.html>.
- `integrations/assaultcube/telemetry.h` and `redteam/assaultcube-client/aegis_lab.h` are
  original Aegis AC code (MIT) that compile into the patched game.
- AssaultCube's game media (maps, textures, sounds, models) have their own copyrights and
  are not used or redistributed here.

Modified clients must not be used on public AssaultCube servers. The lab client enforces
this in code: it only connects to loopback and private LAN addresses.

## Python dependencies (installed by pip, not included)

| Package | Licence |
|---|---|
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| Anthropic Python SDK (optional) | MIT |
| pytest, httpx (development) | MIT, BSD-3-Clause |

## Dashboard dependencies (installed by npm, not included)

| Package | Licence |
|---|---|
| React, React DOM | MIT |
| Vite, @vitejs/plugin-react | MIT |
| TypeScript | Apache-2.0 |
| @types/react, @types/react-dom | MIT |

## Services

- **Claude** (Anthropic API) is used by the optional AI analyst, under Anthropic's terms.
- **Discord** webhooks are used for optional alerts, under Discord's terms.
