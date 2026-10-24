---
name: egotune
description: Tune the closed-loop fuel maps of a DDFI-2 or DDFI-3 Buell from EcmDroid logs with the offline egotune tool, fold the learned AFV into the maps first, review its checks and report, and explain the result to the person. Use when someone wants to correct their fuel maps from a ride log, fold their AFV, review an egotune report, or decide whether a failed check can be accepted.
---

# Tuning fuel maps with egotune

This procedure is for an AI agent, but a person can follow it by hand. The
steps for riders are in [docs/egotune-howto.md](../../docs/egotune-howto.md),
and the command reference in [README.md](README.md).

`egotune` never talks to an ECM and never burns anything. It reads an image
and one or more logs, and writes a new image. The person burns it with
EcmDroid, after reviewing it.

**egotune is in testing.** No map it made has been burned and ridden yet. On
DDFI-2 its map lookup matches the ECM exactly on a real ride; on DDFI-3 that
isn't confirmed yet. Say so whenever you hand over a result.

Run the commands from the repository root, as `tools/egotune/egotune.py …`
(needs [pkgx](https://pkgx.sh)) or `python3 tools/egotune/egotune.py …`
(Python 3.11 or newer).

## Before you start

Ask whether the person has ruled out the causes outside the maps: intake
and exhaust leaks, the engine's condition, static timing, the TPS setting
(DDFI-2), a working O2 sensor, stored trouble codes, and the same fuel every
ride ([how-to](../../docs/egotune-howto.md#before-you-start)). Tuning the maps
hides those faults. If they haven't, say so before anything else.

You need from the person:

- **The image that was in the ECM during the ride** (EcmDroid *Fetch* →
  *Save* right after the last burn). Not an older backup: the corrections only
  fit the maps that produced them.
- **One or more `.bin` logs** recorded with that image, with the engine fully
  warm. The AFV doesn't have to be locked: egotune uses the EGO correction
  alone.
- **The image they started tuning from** (START below), saved after folding
  the AFV (step 0), for `--baseline`. If they don't have it, say that the
  total change over several rounds then isn't limited.

Real images contain the VIN, serial number, odometer and security data. Keep
them and the logs in the git-ignored `xprs/` folder and never commit them.

## Steps

0. **Fold the AFV, once, before the first round.** The person saves the image
   after a calibration ride with the AFV free. Then:
   `egotune fold-afv --image CALIBRATED --out FOLDED.xpr -o FOLD.md`.
   - It multiplies each map by its cylinder's AFV and sets the AFV to 100 %, so
     the fuelling stays the same. Explain that. Never suggest setting the AFV
     to 100 % without folding it in: open loop and WOT would run leaner by the
     same amount.
   - Explain its warnings: an AFV at its learning limit, or more than 10 % from
     100 %, usually points to a cause outside the maps.
   - If it refuses because a cell would go above the map's maximum, the person
     tunes without folding, from the image as it is. Don't cap cells by hand.
   - The person burns the folded image, *Fetch*es and saves it (e.g.
     `iter0.xpr`). That's the image for the first round and the `--baseline`
     for every round.
1. **Analyse:** `egotune analyse --image IMAGE --baseline START LOG… -o REPORT.md`.
   Exit code 0: every check passed. 1: at least one failed. 2: an error
   (wrong files, unknown ECM ID): report it and stop.
2. **Read the checks** at the top of the report. For each failed one, explain
   in plain words what was measured, what the limit is, and what it usually
   means (the report's advice line). Suggest the fix: ride again, check the O2
   sensor, look for an exhaust leak, use the right image, and so on.
3. **Read the warnings and notes**: the image's stored AFV differs from the
   logged one (maybe the wrong image), the front map follows the rear one
   (DDFI-3 without front closed loop), the AFV moved more than 2 % or sat at a
   value other than 100 % (fold it in), no baseline.
4. **Review the maps** in the report:
   - the correction grid: does it change smoothly? Are lean or rich regions
     plausible (lean at low load is common on stock maps)?
   - cells marked `!` (EGO correction at its limit), and the cells listed as
     outlier, noisy or at the baseline limit;
   - the new map: large or isolated changes usually mean bad data;
   - with one O2 sensor (DDFI-2, or DDFI-3 without front closed loop), both
     maps get the same correction from the rear sensor. That's expected. On
     DDFI-3 the person can keep the front map as it is with `--cylinders
     rear`.
   Say what looks odd and why. Say what you don't know.
5. **Apply**, only if the person wants to:
   `egotune apply --image IMAGE --baseline START LOG… --out NEW.xpr -o NEW.md`.
   Use a new file for `--out`. If a check fails, apply writes nothing (exit
   code 1).
6. **Hand over**: the report, `calconv diff IMAGE NEW.xpr` (only the two fuel
   maps may differ), the testing note, and the next steps: burn with
   EcmDroid, *Fetch* and save, ride again, repeat until the report says every
   trusted cell is within ±2 % and the AFV moved less than 2 %.

## Overriding a check

`--accept CHECK` lets apply go ahead although that check fails. The report
then says *Overridden with --accept*. The checks are: `short-log`,
`slow-interval`, `o2-switching`, `ego-limit`, `implausible`,
`global-offset`, `lookup`, `baseline`.

- **Never pass `--accept` on your own.** Explain the failed check, what could
  go wrong, and what would fix it. Pass it only when the person explicitly
  asks for that check by name, after hearing the explanation.
- Never accept `implausible`, `o2-switching` or `ego-limit` to get a result
  "for now": they mean the data can't be trusted. Recommend fixing the cause
  and recording again.
- `lookup` on DDFI-3 can fail because the check isn't confirmed there yet.
  Say so, and recommend extra care with the result.
- `global-offset` can be accepted only after the person has ruled out the
  causes in the advice line (exhaust leak, fuel pressure, vacuum leak, fuel
  change).

## Guardrails

- Never burn, and never tell the person a result is safe. The tool checks the
  data and its own output, not how the engine will run.
- Don't loosen the limits (`--max-rich`, `--max-lean`, `--gain`,
  `--max-from-baseline`, `--min-te`, `--settle`, `--min-seconds`,
  `--full-seconds`) unless the person asks for a
  specific value and understands what it changes. Never loosen them to make
  a check pass.
- Don't change `Tab_CR_Front` or other settings by hand to "help" the tune.
  egotune only changes the two fuel maps (and, with `fold-afv`, the AFV), on
  purpose.
- Never commit real images, logs or reports that contain their private data.
