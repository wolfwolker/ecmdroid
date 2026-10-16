# calconv

`calconv` compares Buell ECM calibration images (`.xpr`/`.epr` EEPROM files)
by variable name, also across firmware layouts (e.g. BUE2D and BUEYD). Later it
will convert a calibration from one layout to another. The plan, rules and
background are in
[docs/calibration-converter.md](../../docs/calibration-converter.md).

**Status:** phases 1–3: `layouts`, `plan`, `info`, `diff`, and `convert` for
variables with identical definitions. `convert` writes a new image and never
changes its inputs. No command talks to an ECM: you burn the result with
EcmDroid or EcmSpy for Mono.

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
| `convert --source TUNE --target ECM --out RESULT` | Carries a tune onto an image of another layout (e.g. BUE2D → BUEYD). The result starts as the target image. Only variables with identical definitions are copied. Page 0, identification, per-unit values (learned AFV, TPS reset voltage, …) and the engine-type check keep the target's value. The report lists what was copied, kept for review, or lost. |

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
```

## Layout

```
calconv.py            command entry point (pkgx/uv shebang, PEP 723 header)
test.py               test runner
calconvlib/db.py      database access: layouts, pages, variable definitions
calconvlib/image.py   reading images, decoding values the way the app does
calconvlib/analysis.py  layout comparison (plan)
calconvlib/diff.py    image comparison (diff)
calconvlib/convert.py conversion (convert)
calconvlib/report.py  Markdown and JSON output
calconvlib/rules.py   rule files
rules/common.toml     rules for every conversion: exclusions, model guard, private data
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
