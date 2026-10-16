# How to Move a Tune to Another ECM

This guide is for riders who want to run a tune made for one Buell ECM on an
ECM with another firmware ID, for example a **BUE2D** tune on a **BUEYD** ECM.
It uses `calconv`, an offline tool in this repository. The background and the
rules are in [calibration-converter.md](calibration-converter.md).

> **Status (October 2026): in testing.** The tool works and checks its own
> result, but no converted image has been burned and ridden yet, and the
> BUE2D → BUEYD rule file still waits for review. **Don't burn a converted
> image on an ECM that runs a motorcycle.** For now, use it to compare images
> and review reports, and tell us what you find (see
> [Beta testing](#beta-testing)). The burning steps below are for when it has
> been validated.

## What it does and doesn't do

- It **reads** two files and **writes** a third one. It never talks to the ECM
  and never burns anything. You burn the result with EcmDroid or EcmSpy for
  Mono, as usual.
- It carries over what both firmwares store the same way: the fuel and spark
  maps with their axes, limits, fan and idle settings, configuration bits and
  so on. For BUE2D → BUEYD that's about 490 of 530 variables.
- It **keeps your ECM's own data**: VIN, serial number, odometer, security
  PIN, stored trouble codes, learned values (AFV), the TPS reset voltage, and
  the calibration and country IDs. So the result still identifies as your ECM.
- It **can't** carry over settings your ECM's firmware doesn't have. On a
  BUEYD, for example, there's no neutral/clutch rev limiter and no speed-based
  fan control. The report lists them.
- It **doesn't decide** what a setting means when the two firmwares use it
  differently. It keeps your ECM's value and asks you to review it.

## What you need

- A PC with Python 3.11 or newer (or [pkgx](https://pkgx.sh)), and a copy of
  this repository.
- **The tune**, as an `.xpr` file, e.g. `tune_BUE2D.xpr`.
- **Your ECM's own image**, read from the ECM that will run the tune: in
  EcmDroid *EEPROM → Fetch*, then *Save*, or with EcmSpy for Mono. It must be
  an `.xpr` (with page 0). Keep this file unchanged: it's your backup.
- Both ECMs must be the same family (DDFI-2 or DDFI-3) and the same engine.
  `calconv` stops if the engine-type setting differs, e.g. an 1125 tune on an
  XB ECM.

Put the files in the `xprs/` folder of the repository. Git ignores it, so your
VIN can't be committed by accident.

## Steps

The commands are run from the repository root. Without pkgx, write
`python3 tools/calconv/calconv.py` instead of `tools/calconv/calconv.py`.

1. **Check both files.**

   ```sh
   tools/calconv/calconv.py info xprs/tune_BUE2D.xpr
   tools/calconv/calconv.py info xprs/my_ecm.xpr
   ```

   Each shows the ECM ID, the calibration ID and the engine-type setting. If a
   file's size fits several ECM IDs, add `--id` with the right one.

2. **Preview the conversion** without any files:

   ```sh
   tools/calconv/calconv.py plan --from BUE2D --to BUEYD
   ```

3. **Convert:**

   ```sh
   tools/calconv/calconv.py convert --source xprs/tune_BUE2D.xpr \
       --target xprs/my_ecm.xpr --out xprs/tune_on_my_ecm.xpr -o xprs/report.md
   ```

   It writes the result only if its own check passes, and it never overwrites
   your files.

4. **Read the report** (`xprs/report.md`). See the next section.

5. **Review** the result. EcmDroid has no map viewer yet, so open the result
   in EcmSpy for Mono (or TunerPro) to look at the maps next to the tune.

While calconv is in testing, stop here. The next steps are for when it has
been validated.

### Burning (after validation)

1. **Burn** the result. With EcmDroid: *EEPROM → Load*, then *Burn* (it needs
   *Enable EEPROM burning* in the settings, and the connected ECM must have
   the same ID as the file). A loaded file is always burned in full, also with
   *Optimized Burning*. Or burn with EcmSpy for Mono.

2. **Check the burn.** Fetch again, save the image, and compare:

   ```sh
   tools/calconv/calconv.py diff xprs/tune_on_my_ecm.xpr xprs/fetched.xpr
   ```

   Pages 1…n must be equal. Page 0 can differ (odometer, trouble codes).

3. **Reset both AFVs to 100 %** (*Setup → AFV Settings*, then *Apply
   Changes*). Your ECM learned them with the old maps.

4. **Test carefully:** start, idle cold and warm, check for trouble codes, and
   ride a short distance with a log. Watch the AFV and the EGO correction.

If something is wrong, burn your original image back.

## Reading the report

| Section | What it means | What to do |
|---------|---------------|------------|
| *Verified* | Every copied value is the tune's, and everything else is your ECM's. | If it says *Verification failed*, don't use the result and report a bug. |
| *Kept: needs review* | Settings both firmwares have, but stored or used differently. Your ECM's value was kept. | Decide each one: leave it, or set it by hand after burning. |
| *Excluded by the rule file* | Settings left out on purpose, with the reason. | Usually set them by hand. For BUE2D → BUEYD that's the idle spark advance table. |
| *Lost* | Tune settings your ECM's firmware doesn't have. | Check whether the tune relies on them, e.g. a configuration bit that's set. |
| *Bitfields: undescribed bits kept* | Configuration bytes where only the documented bits were copied. | Usually nothing. |
| *Copied* | What changed, with your ECM's old value and the new one. | Spot-check the values you know. |
| *Rules* | The rule-file entries that were applied, and the proposed ones that weren't. | See below. |

The report also counts the bytes that the ECM database doesn't describe. They
keep your ECM's values. On DDFI-3 some of them are calibration data that tunes
change (right before the spark tables), so that part of a tune isn't carried
over.

### Rule files

Some conversions need decisions the tool can't make by itself: a setting was
renamed, or its size changed. Those decisions are written down in a rule file
per direction, e.g. `tools/calconv/rules/BUE2D-BUEYD.toml`. An entry only takes
effect once someone has reviewed it (`status = "reviewed"`).

`--allow-proposed` applies the entries that aren't reviewed yet. The report
then shows a warning. Use it to see what a rule would do, not for a file you
burn. For BUE2D → BUEYD it adds the fuel PI controller tables (`Tab_PRF` …):
the BUE2D has five values each and the BUEYD four, and the evidence says the
first BUE2D value is the extra one.

## When it stops

| Message | Meaning |
|---------|---------|
| `fits several layouts` | The file size fits more than one ECM ID. Add `--from`/`--to` (or `--id` for `info`). |
| `model guard: KEng_Ref …` | The engine-type setting differs: the tune is probably for another model. Don't override this unless you know both are the same model. |
| `converting between families isn't supported` | DDFI-2 and DDFI-3 store everything differently. |
| `… exists. Use --force` | The output file exists. Choose another name. |
| `would overwrite an input file` | `--out` is one of your input files. |
| a rule-file error | The rule file has a mistake. The message names the entry. |

## Beta testing

Thanks for helping. Until a converted image has been burned and ridden, the
useful tests are the ones that need no ECM:

- **Run it on your own pairs** of images: `info`, `plan`, `convert`. Does it
  identify your files correctly? Does any command fail or say something
  unclear?
- **Check a result against the tune** in EcmSpy for Mono or TunerPro: fuel and
  spark maps with their axes, rev limits, idle, fan, and the configuration
  bits. Anything that differs from the tune and isn't in the report is a bug.
- **Read the lists in the report:** *Kept: needs review*, *Excluded by the
  rule file* and *Lost*. Is something missing that a tune for your bike
  relies on?
- **Tuners: review the rule file**
  [`BUE2D-BUEYD.toml`](../tools/calconv/rules/BUE2D-BUEYD.toml). Each entry
  has its evidence. Open questions:
  - The fuel PI controller arrays (`Tab_PRF` …) have five values on a BUE2D
    and four on a BUEYD. The rule drops the BUE2D's first value. What does
    that value control?
  - `Tab_Idle_Spark`: BUE2D can use it as the absolute idle advance
    (`KSpark_Config` bit 1), BUEYD adds it to the timing tables. How should a
    BUE2D tune's idle advance be set on a BUEYD?
  - `KPIF1`: 4 bytes on BUE2D, 6 on BUEYD, no description. What is it?
- **Other conversions:** `calconv draft-rules --from A --to B` drafts a rule
  file for another pair, with every entry proposed.

`--allow-proposed` shows what the proposed rules would change. The other open
questions are in
[calibration-converter.md](calibration-converter.md#open-questions).

### What to send

- The commit you used (`git rev-parse --short HEAD`), the command line, and
  the ECM IDs.
- The report, or the part of it that's wrong. The report hides the VIN and
  security data, but it contains your calibration ID and the tune's values.
- For a wrong value: the variable name and what you expected
  (`calconv show VAR --id SRC --id DST --image FILE` prints it).

**Never share the `.xpr` files publicly.** They contain your VIN and serial
number. Send feedback to the person who shared calconv with you, or open an
issue on the [fork](https://github.com/wolfwolker/ecmdroid/issues).
