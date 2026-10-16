# calconv

`calconv` compares Buell ECM calibration images (`.xpr`/`.epr` EEPROM files)
by variable name, also across firmware layouts (e.g. BUE2D and BUEYD), and
converts a calibration from one layout to another. A one-page explanation is
in [docs/calibration-converter-overview.md](../../docs/calibration-converter-overview.md),
and the plan, rules and background in
[docs/calibration-converter.md](../../docs/calibration-converter.md).

**Status:** phases 1–5: `layouts`, `plan`, `info`, `diff`, `convert`, and rule
files for renamed variables and changed shapes (`draft-rules` drafts one).
[SKILL.md](SKILL.md) is the step-by-step procedure for an AI agent or a
person. `convert` writes a new image and never changes its inputs. No command
talks to an ECM: you burn the result with EcmDroid or EcmSpy for Mono.

> **In testing.** No converted image has been burned and ridden yet, and the
> BUE2D → BUEYD rule file still waits for review. Use it to compare images and
> to review conversion reports, but **don't burn a converted image on an ECM
> that runs a motorcycle**. Every conversion report says so too. To help test
> it, see *Beta testing* in the
> [how-to](../../docs/calibration-converter-howto.md#beta-testing).

## Running it

The scripts start with a [pkgx](https://pkgx.sh) shebang that provides
Python 3.11 and [uv](https://docs.astral.sh/uv/). With pkgx installed, run
them directly:

```sh
cd tools/calconv
./calconv.py --help
./test.py            # run the tests (-v for details)
```

Without pkgx, any Python 3.11 or newer works. Only the standard library is
used:

```sh
python3 tools/calconv/calconv.py --help
python3 tools/calconv/test.py
```

By default, `calconv` reads the app's bundled database
(`app/src/main/assets/ecmdroid.db.gz`), so it always uses the same ECM
definitions as EcmDroid. `--db` selects another one.

## Commands

| Command | What it does |
|---------|--------------|
| `layouts` | Lists the ECM layouts, their `.xpr`/`.epr` sizes, and the sizes that fit more than one layout |
| `plan --from ID --to ID` | Analyses two layouts without any files. It shows what a conversion would copy and what it would lose. It also lists definitions that changed, variables whose meaning depends on the firmware, possible renames, and database problems. |
| `info FILE [--id ID]` | Identifies an image by its size and shows the ECM information: calibration ID, country ID, serial number, manufacturing date and the model-guard values |
| `diff FILE_A FILE_B [--id-a ID] [--id-b ID]` | Compares two images by variable name. With the same layout, it also compares raw bytes, including bytes outside any variable. Exit code 0 means identical, 1 different. |
| `convert --source TUNE --target ECM --out RESULT` | Carries a tune onto an image of another layout (e.g. BUE2D → BUEYD). The result starts as the target image. Variables with identical definitions are copied, plus whatever the reviewed entries of the rule file for this direction say. Page 0, identification, per-unit values (learned AFV, TPS reset voltage, …) and the engine-type check always keep the target's value. The report lists what was copied, kept for review, excluded or lost. |
| `draft-rules --from ID --to ID` | Drafts a rule file for a direction from the plan: aliases for rename candidates, transforms where the shapes allow one, exclusions for the rest. Every entry is `proposed`. |

Rule-file options (`plan`, `convert`):

- `rules/<FROM>-<TO>.toml` is used when it exists (also for IDs that share a
  layout, e.g. a B3R2D tune uses `BUE2D-BUEYD.toml`);
- `--pair-rules FILE` uses another file, `--no-pair-rules` none;
- `convert --allow-proposed` also applies entries that aren't reviewed yet.
  The report says so in a banner. Use it to try a rule, not for a burn.

Common options:

- `--format json` gives machine-readable output;
- `-o FILE` writes the report to a file;
- `--all` lists everything, not only what needs attention.

The VIN and security data are hidden unless you add `--show-private`.

Examples:

```sh
./calconv.py plan --from BUE2D --to BUEYD
./calconv.py info my_ecm.xpr
./calconv.py diff before.xpr after.xpr          # e.g. a saved image vs. a fetch after burning
./calconv.py info BUEIB.epr --id BUEIB          # 1206 bytes fits BUEIB/BUEIC and B2RIB
./calconv.py convert --source tune_BUE2D.xpr --target my_ecm_BUEYD.xpr --out tune_on_BUEYD.xpr -o report.md
./calconv.py draft-rules --from BUEIB --to BUECB -o rules/BUEIB-BUECB.toml
```

## Rule files

`rules/common.toml` applies to every conversion. A file per direction, e.g.
`rules/BUE2D-BUEYD.toml`, adds reviewed decisions:

```toml
[pair]
from = "BUE2D"
to = "BUEYD"

[[exclude]]                  # keep the target's value, and say why
var = "Tab_Idle_Spark"
reason = "different meaning: ..."
status = "reviewed"
reviewed_by = "your name"

[[copy]]                     # copy a variable the plan flags, e.g. for its description
var = "Tab_Idle_Spark"
reason = "..."
status = "proposed"

[[alias]]                    # renamed variable; also one-to-many and per bit
from = "K_Fan_Period"        # or "KBaro_Config[6]"
to = "KFan_Period"           # or ["Tab_Fan_Duty_Aft", "Tab_Fan_Duty_Fore"], or "KABP_Config[7]"
evidence = "same label, same shape, same neighbours"
status = "proposed"

[[transform]]                # shape changes: copy_elements or resample_pairs
var = "Tab_PRF"
kind = "copy_elements"
source_start = 1             # 0 = the first element
target_start = 0
count = 4
evidence = "..."
status = "proposed"
```

- Only `reviewed` entries (with `reviewed_by`) are applied, unless
  `--allow-proposed` is given. Exclusions win over everything else.
- An alias copies raw bytes when both definitions are identical. If only the
  scale differs, values are converted and rounded. A value that doesn't fit
  keeps the target's value. Other differences need a transform.
- `copy_elements` copies `count` elements; the rest keep the target's values.
  `resample_pairs` interpolates a self-contained axis/value table onto the
  target's own axis (linear, clamped at the ends).
- No rule can write page 0, identification, per-unit or model-guard variables,
  and two rules can't write the same variable or bit. `calconv` checks every
  entry against the database before converting.

## Layout

```
calconv.py            command entry point (pkgx/uv shebang, PEP 723 header)
test.py               test runner
calconvlib/db.py      database access: layouts, pages, variable definitions
calconvlib/image.py   reading images, decoding values the way the app does
calconvlib/analysis.py  layout comparison (plan)
calconvlib/diff.py    image comparison (diff)
calconvlib/convert.py conversion (convert), rule application and verification
calconvlib/draft.py   rule-file drafts (draft-rules)
calconvlib/report.py  Markdown and JSON output
calconvlib/rules.py   rule files
rules/common.toml     rules for every conversion: exclusions, model guard, private data
rules/BUE2D-BUEYD.toml  rules for BUE2D → BUEYD (proposed, waiting for review)
SKILL.md              procedure for an AI agent (or a person) running a conversion
tests/                unittest suite. It uses the app's test images in app/src/androidTest/resources,
                      and real images in xprs/ when present (git-ignored: they contain VINs)
```

Value decoding follows `Variable.refreshValue()` in the app: little-endian,
unsigned, `size / elemsize` elements, value = raw × scale + translate. The tests
check it against the expectations of the app's instrumented tests.

There are two deliberate differences in what the tool shows:

- **Tables:** the axis half of a self-contained table (the even positions) is
  scaled with `axisscale`/`axistranslate`.
- **Fractional values:** values are never truncated to the display format,
  because the app hides fractions for many variables.
