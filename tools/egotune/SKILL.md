---
name: egotune
description: Tune the closed-loop fuel maps of a DDFI-2 or DDFI-3 Buell from EcmDroid logs with the offline egotune tool, review its checks and report, and explain the result to the person. Use when someone wants to correct their fuel maps from a ride log, review an egotune report, or decide whether a failed check can be accepted.
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

You need from the person:

- **The image that was in the ECM during the ride** (EcmDroid *Fetch* →
  *Save* right after the last burn). Not an older backup: the corrections only
  fit the maps that produced them.
- **One or more `.bin` logs** recorded with that image, warm engine, AFV
  locked at 100 %.
- **The original tune** they started from, for `--baseline`. If they don't
  have it, say that the total change over several rounds then isn't limited.

Real images contain the VIN, serial number, odometer and security data. Keep
them and the logs in the git-ignored `xprs/` folder and never commit them.

## Steps

1. **Analyse:** `egotune analyse --image IMAGE --baseline ORIGINAL LOG… -o REPORT.md`.
   Exit code 0: every check passed. 1: at least one failed. 2: an error
   (wrong files, unknown ECM ID): report it and stop.
2. **Read the checks** at the top of the report. For each failed one, explain
   in plain words what was measured, what the limit is, and what it usually
   means (the report's advice line). Suggest the fix: ride again, check the O2
   sensor, look for an exhaust leak, use the right image, and so on.
3. **Read the warnings**: AFV not locked, AFV changed since the image was
   saved, front map left unchanged (DDFI-3 without front closed loop), no
   baseline.
4. **Review the maps** in the report:
   - the correction grid: does it change smoothly? Are lean or rich regions
     plausible (lean at low load is common on stock maps)?
   - cells marked `!` (EGO correction at its limit), and the cells listed as
     outlier, noisy or at the baseline limit;
   - the new map: large or isolated changes usually mean bad data;
   - on DDFI-2, both maps get the same correction from the rear sensor. That's
     expected.
   Say what looks odd and why. Say what you don't know.
5. **Apply**, only if the person wants to:
   `egotune apply --image IMAGE --baseline ORIGINAL LOG… --out NEW.xpr -o NEW.md`.
   Use a new file for `--out`. If a check fails, apply writes nothing (exit
   code 1).
6. **Hand over**: the report, `calconv diff IMAGE NEW.xpr` (only the two fuel
   maps may differ), the testing note, and the next steps: burn with
   EcmDroid, *Fetch* and save, ride again, repeat until the report says every
   trusted cell is within ±2 %.

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
  change, AFV not locked).

## Guardrails

- Never burn, and never tell the person a result is safe. The tool checks the
  data and its own output, not how the engine will run.
- Don't loosen the limits (`--max-rich`, `--max-lean`, `--gain`,
  `--max-from-baseline`, `--min-te`, `--settle`) unless the person asks for a
  specific value and understands what it changes. Never loosen them to make
  a check pass.
- Don't change `Tab_CR_Front` or other settings by hand to "help" the tune.
  egotune only changes the two fuel maps, on purpose.
- Never commit real images, logs or reports that contain their private data.
