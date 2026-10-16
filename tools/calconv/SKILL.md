---
name: calconv
description: Carry a Buell ECM calibration (a tune in an .xpr file) from one firmware layout to another, e.g. BUE2D → BUEYD, with the offline calconv tool; explain what can't be carried over and draft rule-file entries for review. Use when someone wants to move a tune to an ECM with another ID, compare two ECM images, or review calconv rules.
---

# Converting a calibration with calconv

This procedure is for an AI agent, but a person can follow it by hand. The
background and the rules are in
[docs/calibration-converter.md](../../docs/calibration-converter.md), and the
command reference in [README.md](README.md).

`calconv` never talks to an ECM and never burns anything. It reads two images
and writes a third one. The person burns it with EcmDroid or EcmSpy for Mono,
after reviewing it.

**calconv is in testing.** No converted image has been burned and ridden yet.
Tell the person not to burn a result on an ECM that runs a motorcycle, and
point testers to *Beta testing* in
[the how-to](../../docs/calibration-converter-howto.md#beta-testing).

Run the commands from the repository root, as `tools/calconv/calconv.py …`
(needs [pkgx](https://pkgx.sh)) or `python3 tools/calconv/calconv.py …`
(Python 3.11 or newer).

## Before you start

You need two files from the person:

- **Source:** the tune to carry over, e.g. `my_tune_BUE2D.xpr`.
- **Target:** an image read from the ECM that will run the tune (EcmDroid
  *Fetch* → *Save*, or EcmSpy for Mono), as `.xpr` with page 0. It provides the
  ECM's own data (VIN, serial number, learned values) and the settings only its
  firmware has. Tell the person to keep it unchanged as a backup.

Real images contain the VIN, serial number, odometer and security data. Keep
them in the git-ignored `xprs/` folder, never commit them, and don't use
`--show-private` unless the person asks for it.

## Steps

1. **Identify both images.** Run `calconv info FILE` for each one.
   - If the size fits several layouts, ask the person for the ECM ID and pass
     it with `--id` (`--from`/`--to` for `convert`).
   - Both must be the same family (DDFI-2 or DDFI-3). Between families,
     stop: converting isn't supported.
   - Compare the model-guard values (`KEng_Ref`). If they differ, the tune is
     probably from another model (XB ↔ 1125). Stop and explain.
   - Tell the person the calibration ID of each file, so they can confirm
     they're the right files.
2. **Preview:** `calconv plan --from SRC --to DST`. Explain in plain words how
   many variables carry over, which ones need a decision (different
   definition, meaning that depends on the firmware), which settings the target
   firmware doesn't have, and whether a rule file exists and is reviewed.
3. **Prepare the decisions.** For each item that needs one: kept variables,
   rename candidates, proposed rule entries.
   - Get the facts with `calconv show VAR --id SRC --id DST --image SOURCE
     --image TARGET`: the definitions, the database label and description,
     and the values in both images.
   - Quote the database text when you argue about meaning. Compare shapes and
     values. Say what you don't know.
   - If there's no rule file, `calconv draft-rules --from SRC --to DST -o
     <scratch path>` gives a starting point. Every drafted entry is proposed
     and most need a better reason or evidence.
   - Propose entries with `status = "proposed"` and the evidence. Explain each
     one and let the person decide.
   - Only when the person explicitly confirms an entry, set `status =
     "reviewed"` and `reviewed_by` to the name they give you.
4. **Convert:** `calconv convert --source SOURCE --target TARGET --out RESULT
   -o REPORT.md`. Use a new file for `--out`.
   - `--allow-proposed` applies unreviewed entries. Use it only to show the
     person what a rule would do, never for a file they'll burn.
   - If the exit code isn't 0, nothing was written. Report the error.
5. **Summarise the report**, in this order:
   - verification: it must say *Verified*, otherwise the result can't be used;
   - risky items: *Kept: needs review*, *Excluded by the rule file*, and any
     unreviewed rules applied;
   - lost settings the tune *uses*, e.g. a configuration bit that's set or a
     table that isn't all zeros (for BUE2D → BUEYD: `KSpark_Config`, the
     neutral/clutch rev limiter, the speed-based fan tables);
   - bitfields whose undescribed bits were kept;
   - then the counts.
6. **Next steps for the person** (the report lists them too):
   1. keep the target image as a backup;
   2. compare the result with the tune in EcmSpy for Mono or TunerPro;
   3. while calconv is in testing, don't burn it: report findings instead
      (*Beta testing* in the how-to). The burning steps are in the how-to,
      for when calconv has been validated.

## Guardrails

- Never set `status = "reviewed"` without the person's explicit confirmation.
- Never invent values, axis points, element mappings or transforms. Every
  rule needs evidence from the database text or from real images.
- Never edit `rules/common.toml` to get a variable copied. Its exclusions
  protect per-unit and identification data.
- Never burn, never tell the person to burn a result while calconv is in
  testing, and never tell them a converted file is safe. The tool
  checks that it did what the rules say, not that the engine will run well.
- Don't use `--allow-model-mismatch` unless the person knows both images are
  from the same model and asks for it.
- Never commit real images or reports that contain their private data.
