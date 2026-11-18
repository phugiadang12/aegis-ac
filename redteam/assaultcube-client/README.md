# Lab cheat client (red team, optional)

A modified **open-source AssaultCube client** with a wallhack (ESP) and an aimbot. It
exists to give an anti-cheat a **real cheater to catch in a lab**. This folder is
self-contained: you can use it against Aegis, or against any anti-cheat you run on your
own LAN AssaultCube server.

> **LAN only, enforced in code.** The client refuses to connect to anything except
> 127.x, 10.x, 172.16–31.x and 192.168.x addresses. An `AEGIS LAB BUILD` watermark is
> always on screen. There is no memory reading, no injection, no driver and no
> anti-cheat bypass. Do not use it against real players.

## Quick setup

Requirements: Windows, Git, Visual Studio 2022 Build Tools (C++ workload).

```powershell
# from the aegis-ac folder
.\redteam\assaultcube-client\setup.ps1
```

This clones AssaultCube's source into `.\assaultcube` (or reuses an existing clone), adds
the patch and builds `assaultcube\bin_win32\ac_client_lab.exe`. The normal client isn't
touched.

## Run it

```powershell
cd assaultcube
.\bin_win32\ac_client_lab.exe --home=lab-home --init -t0 "-ename Cheater; connect localhost"
```

If the first-run account screen appears, press **Esc**.

## The menu

Press **Insert** to open or close the menu. **Up/Down** selects a setting and
**Left/Right** changes it. Every setting is also a console command, for example
`/labaimstr 100`, and `/labmenu` toggles the menu from the console (`/labmenu 7` opens it
on row 8, which is handy for screenshots).

The menu is a HUD-style console: numbered rows grouped into **VISUALS** and **AIM ASSIST**,
segmented ON/OFF switches and bars, a live status line (aim profile: subtle / noticeable /
blatant), and an info panel that explains the selected setting and shows its console
command. Sub-options are greyed out while their master switch is off.

| Setting | Console | What it does |
|---|---|---|
| ESP (wallhack) | `labesp` | Show enemies through walls |
| boxes / health bars / names + dist | `labespbox` `labesphp` `labespname` | Turn each part of the ESP on or off |
| Aimbot | `labaim` | Off by default |
| activation | `labaimkey` | `always`, or only `while firing` |
| FOV (deg) | `labaimfov` | How far from the crosshair a target can be (1–180) |
| strength (%) | `labaimstr` | 100 = instant snap (obvious); 10–30 = smooth (subtle) |
| target | `labaimbone` | head / chest |
| visible only | `labaimvis` | Only lock onto enemies you can actually see |

## Suggested test rounds

| Round | Settings | What it tests |
|---|---|---|
| Blatant | strength 100, FOV 180 | Instant snaps: the easiest case for a detector |
| Subtle | strength 15, FOV 10 | Smooth aim: does the detector still catch it? |
| Wallhack only | aimbot off, ESP on | Can the server tell from behaviour alone? |

## Files

| File | Purpose |
|---|---|
| `setup.ps1` | Clone source → apply patch → build |
| `aegis_lab.h` | All the cheat code: ESP, aimbot, menu, LAN lock |
| `client.patch` | 4 small hooks: LAN lock, menu keys, aim update, drawing |
| `build.bat` | MSVC build of the lab client only |
