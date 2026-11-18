# Two-machine demo on one network

Run the demo across two machines on the same Wi-Fi or LAN: for example a **PC** running
the server and Aegis, and a **laptop** joining as a second player.

```
  Laptop (player)  ──Wi-Fi──┐
                            ├──▶ PC: ac_server_aegis.exe ──▶ collector ──▶ scan / dashboard
  PC (player)      ─────────┘
```

## On the PC (host)

1. Find the PC's LAN address: `ipconfig`, then look for the Wi-Fi or Ethernet **IPv4
   Address** (e.g. `10.0.0.3` or `192.168.1.20`).
2. Start the collector and the patched server, as in
   [integrations/assaultcube](../integrations/assaultcube/README.md).
3. **Firewall:** the first time the server starts, Windows asks whether to allow it.
   Allow it on **Private** networks. If the laptop can't connect, check that the Wi-Fi
   is set to *Private* (Settings → Network → Wi-Fi → your network) and that
   `ac_server_aegis.exe` is allowed in *Windows Security → Firewall → Allow an app*.

## On the laptop

The laptop doesn't need Python or any build tools, only the game:

1. Install AssaultCube 1.3.0.2 (the same version as the server).
2. Start the game, press **T** and type `/connect 10.0.0.3` (use the PC's address).

To play the **cheater** from the laptop instead, copy `ac_client_lab.exe` (built on
the PC by [redteam/assaultcube-client](../redteam/assaultcube-client)) into the laptop's
`AssaultCube 1.3.0.2\bin_win32\` folder and start it from that folder. The lab client
only connects to private LAN addresses, so this works on a home network and nowhere
else.

## Demo script (about 5 minutes)

1. **Clean round:** both machines play normally for a minute. Run
   `python -m aegis_detection.scan --db data/lab.db`, and both players should be *clean*.
2. **Cheat round:** one player turns on the lab client's aimbot (Insert → strength 100).
   Play a minute and scan again.
3. **Explain the result** using [LAB.md](LAB.md): what was caught, what was missed and
   why. Talking through the misses usually goes over best with interviewers.
