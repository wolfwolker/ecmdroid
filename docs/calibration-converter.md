# Calibration Converter: Development Plan

> **Status (October 2026): phases 1 and 2 are implemented** in
> [`tools/calconv/`](../tools/calconv/README.md) (`layouts`, `plan`, `info`,
> `diff`). There's no `convert` yet. All numbers come from the bundled database
> (`d00bc92f-20150424`) and the `BUE2D.eeprom` test fixture. They're produced
> by `calconv plan`, and the tests check them.

## Summary

The converter carries a calibration (a "tune") from one ECM firmware layout to
another, for example from a **BUE2D** image to a **BUEYD** image. The user
chooses the source and target. Any two layouts of the same family in the
database are possible. The first supported case is **BUE2D → BUEYD**.

Firmware isn't touched. The converter reads two `.xpr` files and writes a third
one for the target ECM ID. That file is then loaded and burned with EcmDroid
or EcmSpy for Mono, using their usual safety checks.

**Recommendation: build it offline first**, as a small command-line helper
script with reviewed rule files. An optional AI agent skill can help with the
parts that need judgement. The Android app can reuse the same rule files later.

## Why offline first

| Aspect | Offline script (+ skill) | Feature in the Android app |
|--------|--------------------------|----------------------------|
| Speed of development | Fast. No Android build or release cycle, so it can start now. | Waits for app work that comes first (tests, platform updates) |
| Testing | Plain unit tests against the real database and fixtures | Instrumented tests, or a JVM test set-up that doesn't exist yet |
| Review | A report of hundreds of values and map cells, easy to read on a big screen | Hard to review on a phone |
| Burning | Unchanged: the result is an ordinary `.xpr` for EcmDroid or EcmSpy for Mono | Needs new UI on top of the burn path |
| Uncertain cases (renamed variables, changed meaning) | A human, helped by an agent, decides once. The decision is saved in a rule file. | The app must already know every rule |
| Who can use it | Needs a PC (EcmSpy for Mono users have one) | Every EcmDroid user |

It fits the idea that EcmDroid is the tool on the bike, while heavy map
tuning can stay on the PC. The knowledge it builds up (the rule files) is
plain data, so a later app feature doesn't start from zero.

**The role of AI.** An agent helps with the *fuzzy* steps: it proposes
matches for renamed variables, reads the database descriptions for changes in
meaning, explains the report, and drafts rule entries. It is **never** part of
the deterministic path. The script produces the same output for the same
inputs and rules, with or without an agent. Rule entries only take effect once
a human marks them as reviewed.

## Workflow

1. **Get both images.**
   - *Source:* the tune to carry over, e.g. `my_tune_BUE2D.xpr`.
   - *Target:* the target ECM's own image, read with EcmDroid (*Fetch* →
     *Save*) or EcmSpy for Mono. It provides the target's per-unit data, and
     values for settings that only exist in the target firmware. Keep it
     unchanged as a backup.
2. **Preview:** `calconv plan --from BUE2D --to BUEYD` shows, without any
   files, what can be carried over, what is lost and what needs a decision.
3. **Convert:**
   `calconv convert --source my_tune_BUE2D.xpr --target ecm_BUEYD.xpr --out result_BUEYD.xpr`.
   This writes the result and a report (`.md`, plus `.json`/`.csv` for tools).
4. **Decide** the flagged items: accept the default (keep the target value),
   add a rule, or change a value by hand later. Then run the conversion again.
5. **Burn** `result_BUEYD.xpr` with EcmDroid (*Load* → *Burn*) or EcmSpy for
   Mono.
6. **Verify:** fetch again and run `calconv diff result_BUEYD.xpr fetched.xpr`.
   Pages 1…n must be identical.
7. **Check the motorcycle:** start, idle, trouble codes, then a short ride with
   a log (AFV, EGO correction).

## First case: BUE2D → BUEYD

| Group | Count | Handling |
|-------|------:|----------|
| Shared names | 527 | Only 42 are at the same offset in both layouts. |
| …identical definition | 517 | **Copy** 495. Exclude 20 page-0 and 2 identification variables (`CSR`, `Country_ID`). |
| …different definition | 10 | Keep the target value and flag. Details below. |
| Only in BUE2D | 17 | **Lost:** the feature doesn't exist in BUEYD. Report the source values. |
| Only in BUEYD | 6 | Keep the target value. |
| Copyable bitfields | 42 | 26 have bits without a description (empty, "unknown" or "reserved"). Copy only described bits. |
| Rename candidates | 0 | The candidate search (below) finds no renames for this pair. |

*Identical* means the same type, size and element width; the same rows and
columns for tables and maps; the same scale and translate (for tables, also
the axis scale and translate); and the same axis variables for maps. These are
the attributes that change how the app reads the bytes. Scale values within
0.1% count as equal, because the database stores them as text with different
precision (`0.01333` vs `0.013333`). The `elements` column is ignored, like in
the app.

Other pairs, for comparison (`calconv plan`):

| Source → target | Source vars | Target vars | Shared | Identical | Same offset | Source only | Target only |
|-----------------|------------:|------------:|-------:|----------:|------------:|------------:|------------:|
| BUEYD → BUE2D   | 533 | 544 | 527 | 517 |  42 |  6 |  17 |
| BUEZD → BUE2D   | 539 | 544 | 532 | 520 |  76 |  7 |  12 |
| BUEWD → BUE2D   | 519 | 544 | 506 | 489 |  42 | 13 |  38 |
| BUE1D → BUE2D   | 537 | 544 | 534 | 523 |  76 |  3 |  10 |
| BUEOD → BUE2D   | 412 | 544 | 386 | 374 |  37 | 26 | 158 |
| BUE2D → BUE3D   | 544 | 662 | 533 | 472 | 502 | 11 | 129 |
| BUEGB → BUEIB   | 233 | 241 | 233 | 231 | 124 |  0 |   8 |

Variable counts are unique names. The database lists a few variables twice
(e.g. four in BUE3D). On BUEOD, `KVS_RPM_Revs` has two *different*
definitions (1 byte in page 0 and 2 bytes at offset 477). `calconv` uses the
first and reports the duplicate as a database warning.

Copied unchanged: all fuel maps (`Tab_Fuel_Front/Rear` 20×16, `Tab_FuelS_*`),
spark maps (`Tab_Spark_Front/Rear` 14×10, `Tab_TA_Ret`) and the other maps,
each with its axes. Also settings, limits, fan and idle (IAC) tables, the
error mask, and most configuration bits.

**Different definition (10):**

- **`Tab_Idle_Spark`: same name, different meaning.** The database description
  says: "For DDFI-2 and early DDFI-3 (BUEOD ... BUEZD): The interpolated value
  is added to the value of the timing table. For later DDFI-3: The interpolated
  value can be used instead of the Timing Table, depending on the settings of
  the Spark Advance Configuration byte."
  - In the `BUE2D.eeprom` fixture, `KSpark_Config` is `0b1101`. Bit 1 ("Use
    Idle Spark Advance Table as base idle map") is set, and the table holds
    absolute values (13° at 0 °C). On a BUEYD the same numbers would be
    **added** to the timing table.
  - The shape also changes: 6 temperature/advance pairs (12 bytes) on BUE2D,
    4 pairs (8 bytes) on BUEYD. The database says 4×4 for BUEYD, which doesn't
    fit 8 bytes. BUEWD and BUEZD have 2×4, so it's most likely 2×4 as well.
  - **Rule: never copy it. Keep the target's table**, and report the source
    table and `KSpark_Config`.
- **PI controller arrays `Tab_PRF`, `Tab_IRF`, `Tab_PLF`, `Tab_ILF` and their
  `…R` counterparts:** 5 bytes on BUE2D, 4 bytes on BUEYD. The database's
  `elements` column says 4 for both. EcmDroid ignores that column and reads
  `size / elemsize` values, so 5 on BUE2D. The live ecmspy.com data says the
  same (checked October 2026). BUE3D has 5 bytes and 5 elements, and the BUE2D
  offsets step by 5, so 5 values on BUE2D is most likely right. The BUEYD
  arrays have one value fewer, so a rule could copy 4 of the 5 values
  (`copy_elements`). That needs someone who knows what the fifth value
  controls. Until then, keep the target's values and flag.
- **`KPIF1`:** 4 bytes on BUE2D (6 according to `elements`), 6 bytes on BUEYD.
  Same handling.

**Lost on BUEYD (17):**

- the neutral/clutch rev limiter (`KNCRPM_*`, 8 variables);
- the speed-based fan tables (`Tab_VS_Fan_On/Off`);
- the front idle spark table (`Tab_Idle_Spark_Front`);
- the spark configuration byte (`KSpark_Config`);
- `KTMLoad_Max_RPM`;
- the calibration IDs (`Cal_ID`, `KID_*`).

The report should say clearly when the source *uses* one of these, for example
`KSpark_Config` bit 1 set. In that case the BUEYD can't behave the same way.

**Only in BUEYD (6):** `Tab_Fuel_End_SL` with its two axes and `KTA_F1` keep the
target's values. `PC_Run_Stat` and `AMC_KO_Stat` are in page 0.

**Prerequisites for this case:**

- **A BUEYD image to test with.** The repository has none. If one is added as
  a fixture, scrub page 0 first: VIN, serial number, odometer and security PIN.
  (On DDFI and DDFI-2 the serial number is in page 1 instead, at offsets
  12–13.)
  This is a public repository.
- **The BUEYD size question, probably settled.** ecmspy.com's list says 3250
  bytes. The bundled database, the live ecmspy.com data and the EcmSpy for Mono
  installer all say 3272 (3232 + a 40-byte page 0, like BUEWD and BUEZD). So
  3250 is most likely a typo on the list. The first real BUEYD file will
  confirm it.
- **The database inconsistencies above.** Ideally they're resolved, but the
  conversion stays safe while they aren't, because it keeps the target's
  values.

## Matching variables, including renamed ones

Names are the primary key, but there are two traps. **Different names can mean
the same thing** (renames between firmware versions), and **the same name can
mean different things** (`Tab_Idle_Spark`). Matching therefore has three
levels:

1. **Exact name**, plus a definition check (rules 5–7 below).
2. **Reviewed aliases** from the rule files, e.g. `K_Fan_Period → KFan_Period`.
3. **Candidates for review.** These are never applied automatically. For each
   variable without a match, the script scores the unmatched variables of the
   other layout on four signals:
   - the same label (`names.name`);
   - similar names (ignoring case, `_`, suffixes like `_2`/`_LD`, and the
     `Load` ↔ `TP` pattern);
   - the same type and size;
   - the same position between matched neighbours, in offset order.

   The scored list goes into the report, and the agent or a human turns
   confirmed candidates into rule entries.

The candidate search against the current database finds, for example:

| Kind | Example | Layouts |
|------|---------|---------|
| Spelling | `K_Fan_Period` ↔ `KFan_Period` | BUEIB ↔ BUECB |
| Wording | `Tab_Fuel_End_Load` ↔ `Tab_Fuel_End_TP` | BUE3D ↔ BUE2D |
| Suffix | `LFuel1` ↔ `LFuel1_LD` (both "AFV Front") | BUE2D ↔ BUEOD |
| Same label, never in the same layout | `KHys_Load_Lo/Hi` ↔ `KHys_TP_Lo/Hi`, `KTemp_Load_Soft/Hard` ↔ `KTemp_TP_Soft/Hard`, `EDiag4` ↔ `EDiag4_2`, `KShift_Config` ↔ `KShift_Config_2` | DDFI-2/DDFI-3 |
| Same feature, bits moved | `KBaro_Config[6]` ↔ `KABP_Config[7]`, `KBaro_Config[2]` ↔ `KABP_Config[0]` (from `ecm_setup.xml`) | DDFI-2 |
| Split | `Tab_Fan_Duty` → `Tab_Fan_Duty_Aft` + `Tab_Fan_Duty_Fore` | BUEIB → BUECB |
| Not 1:1 | `KShiftT` (value) ↔ `Tab_Shift` (table); `KAMC_n_Lo/Hi` ↔ `KAMC_RPM_n` | – |

So aliases must also work **per bit** for bitfields, and support one-to-many
copies. The last row shows why candidates need a human decision.

## Conversion rules

In order:

1. **Check the inputs.** Each file's size must fit the declared layout
   (`size` for `.epr`, `xsize` for `.xpr`). Stop on unknown layouts or
   different families (DDFI-2 ↔ DDFI-3). Never overwrite an input file.
2. **Start from the target.** Anything not copied keeps the target's value,
   including the bytes no variable describes (3% of BUEYD, 16% of BUE2D).
3. **Never copy page 0.** It holds VIN, odometer, security PIN, manufacturing
   data, stored trouble codes and adaptive values. On DDFI and DDFI-2 the
   manufacturing date and serial number (`KMFG_*`) are in page 1, so excluding
   page 0 doesn't cover them. They must be excluded by name before `convert`
   handles those families.
4. **Never copy identification variables:** `CSR`, `Country_ID`, `Cal_ID`,
   `KID_*`.
5. **Check that it's the same model.** Some variables describe the engine and
   harness, e.g. `KEng_Ref` (crankshaft or camshaft sensor, 36-2 or 32-2
   pattern). If they differ, stop: the source is probably from another model
   (XB ↔ 1125). The list is curated in `common.toml`.
6. **Identical definitions:** copy the raw bytes, with no conversion and so
   no rounding. For bitfields, copy only the bits with a description and keep
   the target's undescribed bits. Report when those differ.
7. **Aliases with a different scale:** decode to physical values, convert,
   round, and check against the range (`low`/`high`). If the value is out of
   range, keep the target value and flag.
8. **Maps and their axes form one group.** Copy a map only if its axes can be
   copied too, and the reverse. Otherwise keep the whole group from the target
   and flag.
9. **Shape changes** only through named, built-in transforms (no free-form
   code):
   - `resample_pairs`: self-contained axis/value tables like
     `Tab_Idle_Spark`, interpolated onto the target's axis;
   - `copy_elements`: the first *n* elements, the rest kept from the target.

   A transform only runs if a reviewed rule asks for it.
10. **Anything else** (different definition, no rule, semantic warning): keep
    the target value and flag it.
11. **Report every variable** with its action and its values (source,
    target before, result) as physical values with units: copied, already
    equal, kept and flagged, lost (source only), target only, excluded.

The script never talks to an ECM.

## Rule files

Rule files are plain data, kept in `tools/calconv/rules/`:

- `common.toml` (exists): exclusions (page 0, identification variables), the
  model-guard list and the private variables that reports hide. It applies to
  every pair.
- One file **per direction**, e.g. `BUE2D-BUEYD.toml`. Directions aren't
  symmetric (see `Tab_Idle_Spark`). The script can offer a reversed alias as a
  candidate, but never applies it automatically.

```toml
# BUE2D-BUEYD.toml
[[exclude]]
var = "Tab_Idle_Spark"
reason = "BUE2D: absolute idle advance when KSpark_Config bit 1 is set; BUEYD: added to the timing table"
status = "reviewed"
reviewed_by = "…"

[[alias]]                       # example from another pair
from = "K_Fan_Period"
to = "KFan_Period"
status = "proposed"             # not applied until "reviewed"
evidence = "same label, same shape, same neighbours"

[[transform]]
var = "Tab_PRF"
kind = "copy_elements"
count = 4                       # BUE2D has 5 values, BUEYD 4
status = "proposed"
evidence = "pending: what does the fifth BUE2D value control?"
```

Exclusions win over transforms and aliases.

Entries marked `proposed` are only listed in the report. To apply them you
need `--allow-proposed`, and the report then says so. TOML is used because it
allows comments and is easy to review in pull requests. Python reads it with
the standard library.

## The helper script

Usage is in [tools/calconv/README.md](../tools/calconv/README.md).

- **Location:** `tools/calconv/`, Python 3.11 or newer, standard library only
  (`sqlite3`, `gzip`, `tomllib`, `argparse`, `json`, `unittest`).
- **Running:** `calconv.py` and `test.py` start with a pkgx shebang
  (`#!/usr/bin/env -S pkgx +python@3.11 uv run --quiet`) and a PEP 723 header
  (`requires-python = ">=3.11"`, no dependencies). So `./calconv.py` works
  wherever pkgx is installed, and `python3 calconv.py` works with any
  Python 3.11+.
- **Database:** read directly from `app/src/main/assets/ecmdroid.db.gz`, so it
  always uses the same database as the app.
- **Value decoding** matches `Variable.java`: little-endian, unsigned,
  `size / elemsize` elements (the `elements` column is ignored, as in the app),
  physical value = raw × scale + translate, negative offsets for page 0. The
  tests check it against the values asserted in `TestVariableProvider` and
  `TestECM`. Reports differ from the app in two ways, on purpose:
  - the axis half of self-contained tables uses `axisscale`/`axistranslate`;
  - values are never truncated to their display format.

  171 variable definitions combine the display format `0` with a fractional
  scale (e.g. 0.25°). The app truncates those values on screen.
- **Commands:**

| Command | Purpose | Status |
|---------|---------|--------|
| `calconv layouts` | List the layouts with their sizes (like `EEPROM.size2id()`), and the sizes that fit several layouts | done |
| `calconv info FILE [--id ID]` | Detect the ID from the size. Show the calibration ID, country ID, `CSR`, serial number, manufacturing date and model-guard values. VIN and security data are hidden unless `--show-private`. | done |
| `calconv plan --from A --to B` | Analyse two layouts without images: groups, exclusions, lost features, rename candidates, firmware-dependent meanings, model guard, database warnings, coverage | done |
| `calconv diff F1 F2 [--id-a …] [--id-b …]` | Compare two images by variable name, also across layouts (an offline form of the planned *EEPROM compare*). For the same layout, also compare raw bytes, including bytes outside any variable. Exit code 1 if they differ. | done |
| `calconv convert --source F --target F --out F [--from A --to B]` | Convert, and write the result and the report | phase 3 |

- **Modules:**
  - done: `db` (layouts and definitions), `image` (read, decode, ECM
    information), `analysis` (plan), `diff`, `rules` (`common.toml`),
    `report` (Markdown and JSON), `cli`;
  - still to come: encoding, `match` (aliases), `convert`.
- **Tests** (`unittest`, no extra packages; `./test.py`).
  - Already there, 48 tests:
    - database access and page layout (like `TestEEPROM`);
    - decoding against the app's expectations;
    - the counts in this document;
    - rename candidates;
    - database warnings;
    - `diff` of identical images, a changed map cell, a changed byte outside
      any variable, a one-digit change in the 8-byte VIN, an image without
      page 0, and two layouts;
    - the command line, including exit codes.
  - Still to come:
    - encoding;
    - `resample_pairs` with known points;
    - converting a layout onto itself only changes the non-excluded variables;
    - BUE2D → BUEYD → BUE2D gives back the original value of every identical
      variable;
    - page 0 and the identification variables are never changed.

## The agent skill

- **File:** `tools/calconv/SKILL.md`. Agent Skills is an open format: a
  Markdown file with a short `name`/`description` header. Agents that support
  skills can load it, and any other agent or a human can follow it as a plain
  procedure. `AGENTS.md` points to it, so the guidance stays vendor-neutral.
  A tool-specific link (e.g. a `.claude/skills/calconv` symlink) is optional.
- **Procedure:**
  1. Ask for the source and target files and their IDs. Run `calconv info`, and
     ask when a size fits several IDs (e.g. BUE2D/B3R2D).
  2. Run `calconv plan`. Explain what will be copied, what's lost and what
     needs a decision.
  3. For each flagged item and rename candidate, quote the database label and
     description, compare the shapes and values, and propose a rule entry with
     `status = "proposed"` and the evidence.
  4. Run `calconv convert` and summarise the report: risky items first, then
     lost features, then counts.
  5. Explain the next steps: backup, load and burn in EcmDroid or EcmSpy for
     Mono, verify with `calconv diff`, then the test ride.
- **Guardrails:**
  - never set `status = "reviewed"` without the user's explicit confirmation;
  - never invent values, axis points or transforms;
  - always quote the database text when arguing about meaning;
  - never burn, and never tell the user that a converted file is safe without
    the review.

## Phases

| Phase | Deliverable | Done when | Size | Status |
|-------|-------------|-----------|------|--------|
| 0 | Inputs: a BUEYD image, the model-guard list, the meaning of the fifth BUE2D PI value and of `KPIF1` | A BUE2D and a BUEYD image are available, and the open questions below have owners | S | open (Python decided; database and BUEYD size checked) |
| 1 | `layouts`, `plan`: layout analysis without images | The counts in this document come out of the tool, with tests | S | **done** |
| 2 | `info`, `diff`: read, decode and compare images | `diff` of the fixture against itself is empty; decoded values match the app | S | **done** |
| 3 | `convert` for exact matches with all exclusions, plus the report | BUE2D → BUEYD produces a valid 3272-byte file and a complete report | M | – |
| 4 | Rule files: aliases (including per bit and one-to-many), `copy_elements`, `resample_pairs` | Reviewed rules for BUE2D → BUEYD. Candidates are listed for the other DDFI-3 pairs. | M | candidate search done (in `plan`) |
| 5 | `SKILL.md` and the `AGENTS.md` pointer | An agent can run a whole conversion from it, and a human can follow it by hand | S | – |
| 6 | Validation and a user how-to | The checks below pass for BUE2D → BUEYD | M | – |
| Later | App integration: port the engine to Java (the "reusable core library" idea), ship the rule files as assets, and add UI on the EEPROM screen | – | L | – |

## Validation

1. **Unit tests** (phase 1–4 list above).
2. **Cross-check in EcmSpy for Mono:** open the source and the result, and
   compare the fuel and spark maps, limits and configuration screens.
3. **Simulator:** serve the result with
   [ecmsim](https://github.com/ecmdroid/ecmsim) (`--xpr result.xpr`, if
   `--list` includes BUEYD), then fetch it with EcmDroid. It must load, and the
   Setup values must look plausible.
4. **Bench or spare ECM:** burn, fetch, `calconv diff` against the result.
5. **Motorcycle:** start, idle at cold and warm temperatures (that's where
   `Tab_Idle_Spark` matters), trouble codes, short ride with a log. Compare AFV
   and EGO correction with logs from the source setup.
6. **Expert review:** an experienced tuner reviews the first real report.

## Risks

| Risk | Mitigation |
|------|------------|
| Same name, different meaning | Semantic warnings from the database descriptions. Directional rules. Keep the target's value by default. Expert review. |
| Errors in the database | Flag definitions where size and elements disagree. Cross-check in EcmSpy for Mono. Fix the database upstream. |
| Wrong layout or a file from another model | Size checks, `info` before converting, model guard (rule 5) |
| A wrong rule | `proposed`/`reviewed` status, evidence fields, reviewed in pull requests |
| A bad burn | The tool doesn't burn. A backup of the target exists. Read back and `diff` after the burn. |

## Decisions

- **Language: Python** (decided October 2026). Python 3.11 or newer, standard
  library only. It's the fastest route and runs on any PC. Most of the value
  is in the rule files and tests, and those carry over if the engine is later
  ported to Java for the app.
- **Launcher: pkgx shebang** with uv and PEP 723 metadata (see *The helper
  script*), with plain `python3` as the fallback.
- **Database: the bundled one is current.** In October 2026, the public
  (non-secret) variables of all 14 layouts on the live ecmspy.com site matched
  the bundled database exactly. The public EcmSpy for Mono installer carries older data (January
  2014). See [database.md](database.md#is-there-a-newer-database).

## Open questions

- **The model-guard list.** Which variables identify the engine and harness
  (`KEng_Ref`, others)?
- **The PI arrays and `KPIF1` on BUE2D.** The data is the same on the live
  ecmspy.com site, so EcmSpy for Mono shows the same thing. What's still
  missing is someone who knows what the fifth PI value and `KPIF1` control, to
  decide whether a rule can copy part of them.
- **Learned values outside page 0.** Do pages 1…n hold adaptive values (TPS,
  idle) that should never be copied?
- **Existing tools.** Does EcmSpy for Mono or TunerPro already offer something
  similar? If so, match its behaviour.
