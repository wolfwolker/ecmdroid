# How calconv Works

A short overview of the calibration converter (`tools/calconv`). The steps are
in the [how-to](calibration-converter-howto.md), and the full design in
[calibration-converter.md](calibration-converter.md).

> **In testing:** don't burn a converted image on an ECM that runs a
> motorcycle yet.

## The idea

The app's ECM database knows, for each ECM ID (BUE2D, BUEYD, …), where every
named setting lives in the EEPROM: offset, size and scale. So calconv can
match settings **by name** across two firmwares.

You give it two files:

- **the tune**, e.g. a BUE2D `.xpr`;
- **your ECM's own image**, e.g. a BUEYD `.xpr`. The result is built on a
  copy of this one.

For every setting, Python decides:

| Case | What happens |
|---|---|
| Same name, stored the same way in both | **Copied** from the tune: maps, limits, fan, idle, … |
| Your ECM's own data: VIN, serial number, AFV, trouble codes | **Kept** from your image, always |
| Exists only in the tune's firmware | **Lost**, and listed in the report |
| Exists only in your ECM's firmware | **Kept** from your image |
| Same name, but a different size or meaning | **Kept** from your image and flagged *needs review*. Python doesn't guess. |

Then it re-reads the result and checks that every copied value is the tune's
and every other byte is still your ECM's. Only then does it write the new file
and a report.

For BUE2D → BUEYD, about 490 of 530 settings carry over automatically. The
flagged ones are what the TOML files are for.

## What the TOML files are

There are two kinds, in `tools/calconv/rules/`.

**1. `common.toml`** is a fixed safety list of settings never to copy: VIN,
serial number, AFV and so on. It's written by hand and rarely changes.

**2. One file per direction**, e.g. `BUE2D-BUEYD.toml`. It records the
decisions for the flagged settings. A real entry:

```toml
[[transform]]
var = "Tab_PRF"            # fuel PI controller array
kind = "copy_elements"
source_start = 1           # skip the BUE2D's first value
count = 4                  # copy its values 2-5 into BUEYD's 4 values
evidence = "BUE2D elements 2-5 = BUEYD elements 1-4 (test images)"
status = "proposed"
```

That means: the BUE2D has 5 values here and the BUEYD 4, so copy values 2–5.
Other entries say "this setting was renamed, copy A into B", or "leave this
one out, the meaning differs".

## Who writes the rule files

| Step | Who |
|---|---|
| A **draft** with guesses, all `proposed` (optional) | **Python**: `calconv draft-rules --from BUE2D --to BUEYD` |
| Finding the **evidence** and writing the reasons | **A person, or an AI helping them**, from the database texts and real images |
| **Approving** an entry: `status = "reviewed"` plus `reviewed_by = "name"` | **A person only**, ideally a tuner. Never the AI and never Python. |
| **Applying** the rules | **Python**, inside `convert` |

Python applies only `reviewed` entries. `proposed` ones are ignored unless you
add `--allow-proposed`, and then the report warns about them.

The AI is never part of the conversion itself. With the same files and the
same rules, Python always produces the same result.

## In short

```
tune.xpr ───┐
            ├─► calconv (Python) ─► result.xpr + report
my_ecm.xpr ─┘          ▲
                       │ reads
   common.toml        (fixed safety list)
   BUE2D-BUEYD.toml   (decisions: drafted by Python or an AI,
                       approved by a person)
```
