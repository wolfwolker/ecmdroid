# How to Tune the Fuel Maps with egotune

This guide is for riders who want to fine-tune the closed-loop fuel maps of a
DDFI-2 (XB 2003–2007) or DDFI-3 (XB 2008+, 1125R/CR) Buell with the stock
narrowband O2 sensors. It uses `egotune`, an offline tool in this repository:
you record a ride with EcmDroid, and egotune turns the log into corrected
front and rear fuel maps in a new `.xpr`. The technical reference is
[tools/egotune/README.md](../tools/egotune/README.md).

The method is the closed-loop method of the ECMSpy Mono user guide
([Tuning Methods](https://ecmspy.com/ug_mono/V2.0/tuning.shtml)): fold the
learned AFV into the maps, ride, average the EGO correction per map cell,
adjust the maps, and repeat until the corrections are small and the AFV stays
put. The preparation comes from the ecmspy.com
[Tuning Guide](https://ecmspy.com/tgv2/guide2.shtml). egotune does the
folding, the analysis and the map changes, and applies only part of each
correction per round, as members of the BuellXB.com thread
[*DDFI-3 tuning with stock O2 sensor*](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3)
recommend.

> **Status (October 2026): in testing.** egotune checks its own result, but
> no map it made has been burned and ridden yet. On DDFI-2 its map lookup
> matches the ECM exactly on a real ride. On DDFI-3 that hasn't been confirmed
> yet, so be extra careful there. Read every report before you burn anything,
> and keep your original image.

> **Warning:** burning the EEPROM changes how your engine runs. A wrong value
> can make the engine run lean, overheat or get damaged. Buells have no knock
> sensor, so a lean mixture under load isn't caught by the ECM.

## How it works

- **In closed loop** the ECM corrects the fuel-map value with the **EGO
  correction**, the feedback from the O2 sensor.
- **In open loop** (WOT, deceleration, transitions) it uses the **AFV**
  (adaptive fuel value) instead.
- The ECM **learns the AFV** from the EGO correction while you cruise steadily.

Both are percentages where 100 % means "no correction". So the EGO correction
alone tells how far a map cell is off: a cell where the ECM kept adding 6 %
fuel is 6 % lean. egotune averages it per map cell and moves each cell part of
the way. The logged injector pulse widths of both test logs (DDFI-2 and
DDFI-3) confirm that the AFV doesn't enter in closed loop, so **you don't have
to lock the AFV**.

The AFV still matters: the ECM applies it in open loop and at WOT. That's why
you fold it into the maps first (step 2). Once the maps are right, the AFV
stays near 100 %.

## What it does and doesn't do

- It **reads** your `.xpr` and one or more `.bin` logs, and **writes** a new
  `.xpr`. It never talks to the ECM. You burn the result with EcmDroid, as
  usual.
- `egotune apply` changes **only the fuel maps** `Tab_Fuel_Front` and
  `Tab_Fuel_Rear`. `egotune fold-afv` changes only the maps and the AFV.
  Every other byte stays the same, and egotune checks that.
- It only uses **warm, steady, closed-loop** data: the engine at the ECM's own
  AFV-learning temperature, no warm-up, acceleration or deceleration
  enrichment, and not in the second after a throttle or RPM change.
- It only changes cells with **enough data**. A cell changes from 5 seconds of
  data, with the full step only from 17 seconds: about 100 records at *No
  Delay*, what ECMSpy Mono asks for.
- It changes each cell **a little per round**: a third of the correction, at
  most +6 % or −3 %. So expect a few rounds. With the image you started from
  as `--baseline`, no cell ever moves more than ±15 % from it.
- It **refuses to write a new image when the data looks wrong**: too short a
  ride, a faulty O2 sensor, implausible readings, a correction that points to
  a problem outside the maps, or the wrong image. See [Checks](#checks).
- **With one O2 sensor** both maps move by the same percentage, cell by cell
  (ECMSpy Mono's *locked percentage*).
  - **DDFI-2** has one O2 sensor, in the rear cylinder, and the ECM applies
    its correction to both cylinders.
  - **DDFI-3** without front closed loop works the same way, and the report
    says so. Add `--cylinders rear` to leave the front map alone.

  The front cylinder runs cooler (it gets the airflow first), and the tune
  already accounts for that with its own front map and `Tab_CR_Front`, a front
  correction over engine temperature. Moving both maps together keeps that
  difference. egotune doesn't change `Tab_CR_Front`.
- **On DDFI-3 with front closed loop** (a front O2 sensor, and BUE3D or *O2
  Setup → Enable Independent Front CL*), each map gets its own correction.
- It **can't** tune open loop or WOT: a narrowband sensor has nothing to say
  there. Those need a wideband sensor.
- It supports **DDFI-2 and DDFI-3** ECMs, not the tube-frame DDFI.

## Before you start

Tuning the maps only helps if the maps are the problem. A leak or a faulty
sensor shows up as a "wrong" map, and tuning it in hides the fault. Check
first, as the [Tuning Guide](https://ecmspy.com/tgv2/guide2.shtml) asks
(section 7.2):

- **No air leaks** in the intake or the exhaust. An exhaust leak before the O2
  sensor makes it read lean, and the ECM adds fuel everywhere.
- **The engine is in sound mechanical condition**, and the **static timing**
  is right (Tuning Guide, Appendix B.2).
- **The throttle position sensor is set.** DDFI-2 needs a TPS reset with a
  computer (Tuning Guide, Appendix B.1).
- **The O2 sensor works**: warm and in closed loop, it keeps switching between
  rich and lean, several times a second.
- **No stored trouble codes** you haven't dealt with.
- **The same fuel for every ride**, the one you normally use. Ethanol makes
  the corrections come out a few percent richer, so don't switch between
  rounds.

## What you need

- EcmDroid and a [supported adapter](user-guide.md#what-you-need).
- A PC with Python 3.11 or newer (or [pkgx](https://pkgx.sh)), and a copy of
  this repository. egotune uses `tools/calconv` too, so keep the two folders
  side by side.

Keep each round's files together and name them so you can tell them apart,
e.g. `iter0.xpr`, `iter0-ride1.bin`, `iter1.xpr`, `iter1.md`. A log only fits
the image that was in the ECM while it was recorded.

## Steps

### 1. Save your tune

*Fetch*, then save the `.xpr`, e.g. as `original.xpr`. It's your way back:
keep it unchanged.

### 2. Fold the learned AFV into the maps

1. **Let the ECM learn.** With the AFV limits at their normal values (*O2
   Setup → AFV Settings → Maximum/Minimum AFV (%)*), ride warm for a while
   with some steady cruising.
2. ***Fetch* and save** the image, e.g. as `calibrated.xpr`.
3. **Fold:**

   ```sh
   tools/egotune/egotune.py fold-afv --image calibrated.xpr --out folded.xpr
   ```

   This multiplies every used cell of each map by its cylinder's AFV and sets
   the AFV to 100 %. DDFI-2 has one AFV for both maps. DDFI-3 has one per
   cylinder: *AFV (Rear)* for the rear map, *AFV (Front)* for the front map.
   The fuelling stays the same, but the AFV starts again from 100 %.
4. **Burn `folded.xpr`, *Fetch* again and save** it as `iter0.xpr`. Check that
   the AFV values are exactly 100 (see
   [known issues](user-guide.md#known-issues)). This is the image you tune
   from, and your `--baseline` for every round.

- If the AFV is already 100 %, there's nothing to fold: `iter0.xpr` is simply
  `calibrated.xpr`.
- `fold-afv` warns when the AFV sits at its learning limit, or is more than
  10 % away from 100 %. That usually means something outside the maps (see
  [Before you start](#before-you-start)).
- It refuses when a cell would go above the map's maximum (255). Capping that
  cell would make the engine leaner there than it runs now. Then skip the
  fold and tune from `calibrated.xpr` with the AFV as it is: egotune's
  corrections don't depend on it.

**Don't just set the AFV to 100 % without folding it in.** A bike that had
learned 110 % would then run about 10 % leaner in open loop and at WOT on every
ride.

Leave the AFV limits as they are: the AFV doesn't have to be locked. Its
movement during a ride tells you whether the closed-loop area is right on
average, as ECMSpy Mono uses it.

### 3. Record a ride

1. In the *Log Recorder*, choose the interval *No Delay* or *250 ms*.
2. Warm the engine up fully: at least the ECM's AFV-learning temperature
   (*O2 Setup → AFV Settings → Min. Engine Temp (°C)*, 130 °C on the test
   images; ECMSpy Mono asks for 160 °C on an air-cooled XB).
3. Ride for **at least 30 minutes**, calmly, without hard acceleration or
   overrun. To cover the map, ride at a steady speed in a high gear for 15–20
   seconds, then shift down at the same speed, and repeat up to the top of the
   closed-loop area (about 5000 rpm on an XB).
4. Copy the `.bin` file to your PC, e.g. as `iter0-ride1.bin`. You can record
   several rides and use them together.

### 4. Look at the corrections

```sh
tools/egotune/egotune.py analyse --image iter0.xpr --baseline iter0.xpr iter0-ride1.bin
```

This writes nothing. Read the report (see [Reading the report](#reading-the-report)).
If a check failed or there are warnings, sort them out first.

### 5. Make the new image

```sh
tools/egotune/egotune.py apply --image iter0.xpr --baseline iter0.xpr iter0-ride1.bin --out iter1.xpr -o iter1.md
```

If a check fails, nothing is written and `iter1.md` says why. `iter1.md` is
the report. Check the new map grids: large or isolated changes usually mean
bad data, not a bad map. `calconv diff iter0.xpr iter1.xpr` lists exactly what
changed.

### 6. Burn and repeat

Burn `iter1.xpr` with EcmDroid, *Fetch* and save it again, ride, and run
egotune on the new image and the new log, always with the same
`--baseline iter0.xpr`. Stop when the report says that:

- every cell with enough data is within ±2 %, and
- the AFV moved less than 2 % during the ride.

Stop too when cells keep going back and forth between rounds.

### 7. Afterwards

Ride for a while and check the AFV now and then (*Data Channels*). If the maps
are good, it stays close to 100 %, between about 95 and 105 %.

## Checks

Before it writes anything, egotune checks the data as a whole. If a check
fails, `apply` writes nothing. The report lists every check with what it
measured and the limit, and for each failed one what usually causes it:

| Check | Fails when | What to do |
|---|---|---|
| `short-log` | less than 5 minutes of usable data | Ride longer after a full warm-up, with steady throttle in closed loop. Several logs can be combined. |
| `slow-interval` | records more than 0.5 s apart | Record with *No Delay* or 250 ms. |
| `o2-switching` | the O2 sensor hardly switches between rich and lean | Check the sensor: it may be worn, contaminated or disconnected, or its heater may have failed. |
| `ego-limit` | the EGO correction sits at its limit too often | The mixture is far off or the sensor reads wrong. Look for exhaust leaks, a faulty sensor or a wrong base map. |
| `implausible` | readings out of range or jumping faster than an engine can | Check the sensors, the wiring and the adapter connection. |
| `global-offset` | nearly the whole map is off in the same direction by more than 6 % | Look for a cause outside the maps first (see [Before you start](#before-you-start)): an exhaust leak before the O2 sensor (reads falsely lean, common on Buells), fuel pressure, a vacuum leak, a fuel change. |
| `lookup` | egotune's map lookup doesn't match what the ECM logged | Use the image that was in the ECM during the ride (saved right after the last burn). On DDFI-3 this check isn't confirmed yet. |
| `baseline` | a cell wants to move more than ±15 % from the image you started from | A drift that large usually has a cause outside the maps. |

When you've found that a failed check doesn't apply to you, you can let
`apply` go ahead with `--accept NAME`, e.g. `--accept global-offset` after
you've ruled out an exhaust leak. The report then says so at the top. Don't
accept `o2-switching`, `ego-limit` or `implausible`: they mean the data
can't be trusted. Fix the cause and record again.

## Reading the report

The top lists the files, how many records were used and why the others were
left out, the temperature the engine counted as warm from, and then the
checks. Then, per cylinder:

- **The summary**: how many cells have enough data, how far they are off, and
  the AFV during the ride (at the start, at the end, and its range).
- **Correction the ECM needed**: the mean correction per cell, in %. A
  positive value means the cell is lean and gets more fuel. Values in
  *italics* have less than 5 s of data and aren't used. `!` marks a cell where
  the EGO correction sat at its limit: the real error is bigger than shown.
- **Data**: the seconds of data per cell. The heading says how many records
  that is at your log's interval.
- **New map**: the map after this round. Changed cells show **new** (old).
  The summary lists the cells that were left alone: *outlier* (far from its
  neighbours: real maps change smoothly), *noisy* (the correction jumps
  around within the cell) and *baseline limit*.

Warnings and notes, and what to do about them:

| Warning or note | What to do |
|---|---|
| The image stores a different AFV and asks whether it was in the ECM | You probably used the wrong image. Use the one you saved right after the last burn. |
| The front map follows the rear correction (DDFI-3) | Your ECM has no front closed loop, so the front map moves with the rear one. Add `--cylinders rear` if you'd rather leave it alone. |
| The AFV is constant but not 100 % | Fold it into the maps (step 2), so it starts from 100 %. |
| The AFV moved more than 2 % | The closed-loop area is still off on average, or the altitude or weather changed. Keep going. |
| No `--baseline` given | Pass the image you started tuning from (`iter0.xpr`), so the total change stays limited. |

## Settings

The defaults follow the method. Change them only if you know why:

| Option | Default | What it does |
|---|---|---|
| `--gain` | 0.33 | part of each correction applied per round |
| `--max-rich`, `--max-lean` | 6, 3 | most a cell may gain or lose per round, in % |
| `--min-seconds` | 5 | data a cell needs before it's changed |
| `--full-seconds` | 17 | data at which a cell gets the full gain |
| `--min-te` | the image's | warm engine from, in °C: the ECM's AFV-learning temperature (`KLCL_Min_TE`) |
| `--settle` | 1 | seconds skipped after a throttle or RPM change |
| `--cylinders` | both | `front` or `rear` to tune just one map |
| `--baseline` | none | the image you started tuning from: no cell moves further from it than `--max-from-baseline` |
| `--max-from-baseline` | 15 | in % |
| `--accept` | none | let `apply` go ahead although a named check fails (see [Checks](#checks)) |

Raising the caps makes each round bigger, and a lean mistake is the dangerous
one.
