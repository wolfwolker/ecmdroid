# egotune

`egotune` automates narrowband fuel-map tuning for DDFI-2 (XB 2003–2007) and
DDFI-3 (XB 2008+, 1125R/CR) ECMs. The steps for riders are in
[docs/egotune-howto.md](../../docs/egotune-howto.md). It
reads EcmDroid's binary logs (`.bin`) and the `.xpr` image that was in the ECM
during the ride. It works out how much the ECM had to correct each fuel-map
cell and writes a new `.xpr` with corrected `Tab_Fuel_Front` and
`Tab_Fuel_Rear` maps. You don't need MegaLogViewer, `.msl` files, a
spreadsheet or a map editor.

> **In testing.** No map made by egotune has been burned and ridden yet. On
> DDFI-2 its map lookup matches the ECM exactly on a real ride (see the lookup
> check below). On DDFI-3 that hasn't been confirmed yet. Review every change
> before you burn it, and keep your original image.

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
   locked at 100 % (recommended), that's just the EGO correction.
   - **DDFI-3:** the rear cylinder uses `FBFuel`, `LFuel_LD` and `RLoad`, the
     front `FBFuel1`, `LFuel1_LD` and `FLoad`.
   - **DDFI-2:** there's one O2 sensor, in the rear cylinder, one AFV and one
     load (`FBFuel`, `LFuel_LD`, `RLoad`). The ECM applies that one EGO
     correction to both cylinders, so egotune puts it into both maps. Both
     maps then move by the same percentage, which keeps the front/rear
     difference of the tune: the difference between the two maps, and
     `Tab_CR_Front`, the front-cylinder correction over engine temperature
     that the ECM applies after the map lookup. egotune doesn't change
     `Tab_CR_Front`.
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
     aren't. On DDFI-2 each map row ends with an unused byte (`skip` in the
     database), which isn't touched either.
6. **DDFI-3: leaves the front map alone** if the front EGO correction doesn't
   move, or is just a copy of the rear one. Either way, the ECM has no front
   O2 feedback to tune from.

## Checks and warnings

- **Lookup check.** The runtime frame also carries the ECM's own map lookup
  (`TabFuel1_Raw` front, `TabFuel2_Raw` rear). egotune recomputes it from the
  image. If the two don't follow each other (a spread above 5 %), the image
  probably isn't the one that was in the ECM during the ride, or the lookup is
  wrong for that ECM. It's a warning, not an error.
  - **DDFI-2: confirmed.** On the app's BUEIB test image and log (a 42-minute
    ride), the logged value is exactly 37.5 × the map lookup for both maps on
    all 13,982 records. 37.5 is the scale of the channel (1 / 0.026666). This
    confirms the map layout (including the skipped byte at the end of each
    row), the axes, the bilinear lookup and the load channel.
  - **DDFI-3: open.** On the BUE2D test image and log, the factor is 58–69
    instead of 37.5, with a spread of 8 % (rear) and 20 % (front), and it
    drifts with load. Those two files don't belong together (the image stores
    a rear AFV of 87.9 %, the log shows 100 %), but a different tune alone
    hardly explains a factor that far off. DDFI-3 may compute the logged value
    differently, or the logged load may not be exactly what indexes the map.
    This needs a DDFI-3 log with the image it was recorded with.
- **AFV.** egotune warns if the image's AFV limits aren't locked at 100 %, if
  the live AFV moved during the ride, or if the image's stored AFV differs from
  the logged one. When the lookup check matches, that difference only means the
  AFV changed since the image was saved, and the warning says so.
- **EGO limit.** A cell whose EGO correction sat at the image's
  `KFBFuel_Max`/`KFBFuel_Min` for at least 20 % of its data is marked `!`. The
  real error there is bigger than the mean shows.
- **Done.** The report says when every cell with enough data is within ±2 %:
  that region is tuned.

## What it doesn't do

- Talk to the ECM. You lock the AFV, record, fetch and burn with EcmDroid (or
  EcmSpy for Mono).
- Open loop or WOT. Narrowband data can't tune them; they need a wideband sensor.
- DDFI (tube-frame) ECMs. The database has their maps, but there's no test
  log to check egotune against, so it refuses them.
