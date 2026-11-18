# Telemetry mutation: testing for cheats we don't have yet

Cheat developers will build silent aim and triggerbots whether or not the lab has them.
The question for an anti-cheat team is: **would we catch them, and how subtle can they be
before we don't?**

The server never sees a cheat, only the telemetry it produces. However a cheat is built,
it has to change that telemetry in a specific way to work. So instead of building cheats,
Aegis takes a **real recorded match** and changes only the part of the telemetry a given
cheat would have to change. Movement, aim noise, timing and the other players all stay real.

| Mutation | What changes in the real match | The footprint it tests |
|---|---|---|
| `silent_aim` | Each hit leaves *level* degrees away from where the player was looking | Shot direction ≠ view |
| `triggerbot` | In *level* (0–1) of engagements, a shot fires on the tick the crosshair reaches the enemy | Reaction faster than one tick |
| `smooth_lock` | At each shot, the crosshair is pulled *level* (0–1) of the way onto the enemy | Lock-on tighter than human aim |

Mutated matches are saved as new matches (`<match_id>-mut-<kind>-<level>`), validated by
the collector's schema like live telemetry. The original events are never changed.

## Commands

```powershell
# sweep every mutation over a range of strengths on one player
python -m aegis_detection.mutate --db data/lab.db --match ac-1794961039-2 --sweep

# one mutation only, or a specific player
python -m aegis_detection.mutate --db data/lab.db --match ac-1794961039-2 --kind silent_aim --player Cheater

# save one mutated copy, then run the SOC agent on it like any real match
python -m aegis_detection.mutate --db data/lab.db --match ac-1794961039-2 --kind silent_aim --level 20 --save
python -m aegis_soc --db data/lab.db --match ac-1794961039-2-mut-silent_aim-20 --watch
```

Outcomes in the sweep table:
- **caught**: flagged as `cheat_like` with the right cheat type.
- **review**: `skill_or_cheat`, so it goes to a human, not to a ban.
- **missed**: nothing raised.
- **(wrong type)**: something else was named first.

## Results on the real lab matches

The base player is the lab "Cheater" from the two real aimbot rounds. That's why every
baseline row already says `skill_or_cheat / aimbot`: it's the real aimbot's tight lock.

### Silent aim: the floor moved from 25° to 15°

| Offset | First run (25° total limit) | After the fix |
|---|---|---|
| 5°, 10° | missed | missed (inside normal spread) |
| 15°, 20° | **missed** | **caught**, `silent_aim`, `cheat_like` |
| ≥ 25° | caught | caught |

**What the sweep found:** with a single 25° limit, a careful silent aim at 15–20° got
through. Measuring all 53 real shots showed that the spread is mostly **vertical**: up to
14.4° of recoil, but never more than **6.9° sideways**. So I added a separate 12° sideways
limit.

**What the simulator then caught:** the new limit raised false positives from 1 to 16 in
480 simulated legit players. A player who turns while firing has moved up to about 12°
between two ticks, so a normal shot looked "off-view". The fix: compare each shot with
the view **before and after** it, and only count it if it's far from both. False positives
went back to 1 in 480, and the 15° floor stayed.

**Known limit:** a player turning fast gets about 12° of slack in the direction they're
turning. A silent aim that only fires along the turn could hide inside that.

### Triggerbot: needs more engagements than one short round has

| Share of engagements | Match 2 (≈ 9 engagements) | Match 3 |
|---|---|---|
| 10–25% | review (aimbot) | review (aimbot) |
| 50–75% | review (aimbot) | **missed: clean** |
| 100% | **caught**, `triggerbot` | **caught**, `triggerbot` |

Two findings:
1. **Sample size.** The rule needs 8 measured engagements so that a few lucky fast shots
   can't flag a human. These real rounds only have about 9, so only a 100% triggerbot is
   caught. The answer is to combine evidence **across matches** (player history), not to
   lower the minimum.
2. **One signal hid another.** In match 3, adding triggerbot shots made the player look
   **cleaner**. The injected shots sit 2–4° from the enemy, which pushed the *median* lock
   error from 2.2° to just over the 2.5° limit, so the aimbot signal disappeared. A
   median-based rule can be diluted. A more robust version would count *how many* shots
   are extremely tight, not just look at the middle value.

### Smooth lock: measured, but never more than "review"

The lock error falls exactly as expected (1.42° → 0.71° → 0.00° in match 2), but the
outcome stays **review**. That's on purpose: the lock-on rule is provisional until real
human rounds show how tight good players aim (see [PENTEST.md](PENTEST.md) §6). Until
then, the SOC agent never bans on lock-on alone.

## How this fits the pentest

- [PENTEST.md](PENTEST.md) tests the cheats the lab client really has (aimbot, ESP) on live
  matches.
- This tool tests the cheats it doesn't have (silent aim, triggerbot), on the same real
  telemetry.
- After the human baseline rounds (R1–R2), run the sweep on an **honest** player's match.
  That is the cleanest test of all: real human aim with exactly one cheat footprint added.
