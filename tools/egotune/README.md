# egotune

`egotune` automates narrowband fuel-map tuning for DDFI-3 ECMs (XB 2008+,
1125R/CR). The steps for riders are in
[docs/egotune-howto.md](../../docs/egotune-howto.md). It
reads EcmDroid's binary logs (`.bin`) and the `.xpr` image that was in the ECM
during the ride. It works out how much the ECM had to correct each fuel-map
cell and writes a new `.xpr` with corrected `Tab_Fuel_Front` and
`Tab_Fuel_Rear` maps. You don't need MegaLogViewer, `.msl` files, a
spreadsheet or a map editor.

> **In testing.** No map made by egotune has been burned and ridden yet, and
> the lookup check (below) hasn't been confirmed on a log and the image it was
> recorded with. Review every change before you burn it, and keep your
> original image.

## Running it

It uses calconv's database and image code (`tools/calconv/calconvlib`), so it
needs the calconv folder next to it. Like calconv, it runs with
[pkgx](https://pkgx.sh) or any Python 3.11 or newer, and uses only the
standard library.

```sh
tools/egotune/egotune.py analyse --image iter0.xpr ride1.bin ride2.bin
tools/egotune/egotune.py apply   --image iter0.xpr ride1.bin ride2.bin --out iter1.xpr -o iter1.md
tools/egotune/test.py            # tests (or: python3 tools/egotune/test.py)
```

| Command | What it does |
|---------|--------------|
| `analyse` | Reports the corrections per cell, the data behind them and the changes it would make. Writes nothing. |
| `apply --out FILE` | Also writes the new image: the input image with only the fuel-map bytes changed, read back and checked. It never overwrites an input, or an existing file unless you add `--force`. |

`--format json` gives machine-readable output, and `-o FILE` writes the report
to a file.

## What it does

1. **Reads the logs** with the runtime definitions from the app's database.
   Records with a bad checksum are dropped. The log's ECM ID selects the
   layout. Add `--id` for logs recorded as `UNKWN`.
2. **Keeps only usable records**: engine running, closed loop (`Flags2` bit 7)
   and not WOT, engine at least 71 °C (`--min-te`), no warm-up enrichment
   (`CrTE` at most 100.5 %, `--max-warmup`), no acceleration or deceleration
   enrichment (`Flags1`, `CrAcc`), and at least 1 s (`--settle`) after any
   transient. A transient is an RPM or load jump, a gap in the log, an
   enrichment event or the start of closed loop. The report counts what was
   left out and why.
3. **Works out the correction per cylinder** as EGO × AFV / 100. With the AFV
   locked at 100 % (recommended), that's just the EGO correction. The rear
   cylinder uses `FBFuel` and `RLoad`, the front `FBFuel1` and `FLoad`.
4. **Spreads each record over the four cells around it**, with the same
   bilinear weights the ECM uses to read the map, and weights it by the time
   it covers. Each cell gets the time-weighted mean correction and its seconds
   of data.
5. **Proposes new values**: `new = old × (1 + gain × confidence × (correction/100 − 1))`.
   - The gain is ⅓ (`--gain`).
   - Confidence rises with the cell's data and reaches 1 at 10 s
     (`--full-seconds`).
   - Cells with less than 2 s of data (`--min-seconds`) keep their value.
   - A change is capped at +6 % (`--max-rich`) and −3 % (`--max-lean`) per
     iteration, because there's no knock sensor.
   - The result is rounded to the map's resolution. A change that rounds away
     is listed as *below resolution*.
   - Only the breakpoints in use are touched: unused, zero-padded axis entries
     aren't.
6. **Leaves the front map alone** if the front EGO correction doesn't move, or
   is just a copy of the rear one. Either way, the ECM has no front O2
   feedback to tune from.

## Checks and warnings

- **Lookup check.** The runtime frame also carries the ECM's own map lookup
  (`TabFuel1_Raw`, `TabFuel2_Raw`). egotune recomputes it from the image. If
  the two don't follow each other (a spread above 5 %), the image probably
  isn't the one that was in the ECM during the ride. Until this check has been
  confirmed on a matching image and log, the result is a warning, not an
  error. On the app's test fixtures (`BUE2D.eeprom` and `BUE2D_log.bin`) the
  spread is 8 % (rear) and 20 % (front). Those two files weren't recorded
  together: the image stores a rear AFV of 87.9 %, while the log shows 100 %.
- **AFV.** egotune warns if the image's AFV limits aren't locked at 100 %, if
  the live AFV moved during the ride, or if the image's stored AFV differs from
  the logged one.
- **EGO limit.** A cell whose EGO correction sat at the image's
  `KFBFuel_Max`/`KFBFuel_Min` for at least 20 % of its data is marked `!`. The
  real error there is bigger than the mean shows.
- **Done.** The report says when every cell with enough data is within ±2 %:
  that region is tuned.

## What it doesn't do

- Talk to the ECM. You lock the AFV, record, fetch and burn with EcmDroid (or
  EcmSpy for Mono).
- Open loop or WOT. Narrowband data can't tune them; they need a wideband sensor.
- DDFI and DDFI-2 ECMs. Their maps and runtime data are laid out differently.
