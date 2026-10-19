# Narrowband Fuel-Map Tuning (DDFI-3)

A method for fine-tuning the fuel maps of a DDFI-3 Buell (XB 2008+, 1125R/CR)
with the stock narrowband O2 sensors: log a ride with the adaptive fuel value
(AFV) locked, find out how much the ECM had to correct each map cell, and fold
those corrections back into the maps.

> **Source.** Adapted from the post "OE Narrowband Tuning"
> ([#124, 6 March 2018](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/post-599001))
> in the BuellXB.com thread
> [*DDFI-3 tuning with stock O2 sensor*](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/).
> The author built it over about ten years of tuning Buells and used it on an
> '08 XB12Ss and an '09 1125CR. The text has been reorganised and clarified,
> EcmDroid equivalents have been added, and so have findings from the rest of
> the thread, each linked to the page it comes from. The method is the
> author's. The refinements marked *(EcmDroid)* aren't from the thread: they
> come from the ECM definitions in the app's database, and the offline tool
> [egotune](../tools/egotune/README.md) applies them for you.

> **Warning:** burning the EEPROM changes how your engine runs. A wrong value
> can make the engine run lean, overheat or get damaged. Buells have no knock
> sensor, so a lean mixture under load isn't caught by the ECM. Always keep a
> backup of the original EEPROM (`.xpr`) and double-check every change before
> you burn it.

## How it works

In closed loop the ECM trims fuel with the **EGO correction** (short-term O2
sensor feedback) and learns a long-term **AFV** per cylinder, which it also
applies in open loop. Both are percentages where **100 % means "no
correction"**. See the [glossary](glossary.md#terms).

If you lock the AFV to 100 %, every deviation the ECM sees has to show up in
the EGO correction. Averaging the EGO correction per RPM × load cell over a
ride tells you how far each fuel-map cell is off:

```
new cell value = old cell value × EGO correction / 100
```

Example: a cell that averaged 106 % EGO correction was 6 % lean, so it is
multiplied by 1.06.

### What the fuel maps look like *(EcmDroid)*

Each cylinder has its own map, `Tab_Fuel_Front` and `Tab_Fuel_Rear`, with
16 rows × 20 columns:

- **Columns: RPM** (`Tab_Fuel_RPM_Ax`). Not every firmware uses all 20. The
  BUE2D test image uses 17, from 800 to 8000 rpm, and the last three
  breakpoints are 0.
- **Rows: load** (`Tab_Fuel_Load_Ax`, 10 to 255). Load isn't the throttle
  position: the ECM works it out from throttle and manifold pressure (tables
  `Tab_TP_Load`, `Tab_MAP_Load` and `Tab_TP_Weight`), separately per cylinder.
  The live data has both: *Load Front* (`FLoad`) and *Load Rear* (`RLoad`). So
  sort the data by **load**, not by throttle, or samples land in the wrong
  rows.

The ECM doesn't read one cell: it **interpolates** between the four cells
around the current RPM and load. A sample halfway between two breakpoints says
as much about one cell as about the other.

### What the ECM aims for

Figures quoted in the thread
([page 2](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-2),
[page 5](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-5)):

| Region      | Stock enrichment             | Approx. AFR                  |
|-------------|------------------------------|------------------------------|
| Closed loop | none (O2 feedback)           | 14.7:1 (stoichiometric)      |
| Open loop   | +5 %                         | 14.0:1                       |
| WOT         | +10 % (XB), +9 % total (1125) | 13.5:1 (XB), 13.4:1 (1125)  |

### What a narrowband sensor can and can't tell you

A narrowband O2 sensor only says whether the mixture is richer or leaner than
stoichiometric (λ = 1). It works as a switch, not a gauge: in closed loop its
voltage keeps flipping between low and high, and it never measures a specific
AFR. Moving the O2 voltage thresholds in EcmDroid's *O2 Setup* doesn't set a
target AFR either.

The ECM also keeps **reporting** an EGO correction in open loop, but doesn't
**apply** it there. When the throttle goes wide open, the logged EGO value
freezes at the last closed-loop correction and stays there until the ECM goes
back into closed loop
([page 2](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-2)).
Tools that don't know about this, such as MegaLogViewer and TunerPro's history
tables, show those frozen values as if they were real corrections for
open-loop cells.

The EGO correction is also **limited**: *EGO Correction Maximum/Minimum*
(`KFBFuel_Max`/`KFBFuel_Min`) in the EEPROM. If a cell sits at the limit, the
ECM added (or removed) all the fuel it may, and the real error is bigger than
the logged value. Treat such a cell as "at least this far off".

So this method tunes the **closed-loop** cells only. For open loop and WOT you
need a wideband sensor (see [Going further](#going-further)).

## What you need

- **A logger.** Either:
  - an Android phone with **EcmDroid**, which records binary logs (`.bin`)
    and can convert them to `.msl` for MegaLogViewer (see
    [Log Recorder](user-guide.md#log-recorder)); or
  - a laptop with [TunerPro RT](https://www.tunerpro.net) and the Buell ADX
    (datalog definition) for your ECM, as compact as possible, plus straps or
    some other way to fasten it securely to the seat or tank.
- **A Buell ECM interface**: a cable you build yourself or buy pre-made, or for
  EcmDroid any of the [supported adapters](user-guide.md#what-you-need).
- **A way to turn the log into corrections**, one of:
  - **[egotune](../tools/egotune/README.md)** *(EcmDroid, in testing)*: an
    offline tool that reads the EcmDroid `.bin` logs and your `.xpr`, and
    writes a new `.xpr` with corrected front and rear maps. It needs a
    computer with Python 3.11 or newer, and nothing else;
  - **[ECMSpy Mono](glossary.md#related-software)**: opens EcmDroid's `.bin`
    logs and builds per-cell EGO correction maps itself, averaging **only
    closed-loop data**. Several people in the thread log with EcmDroid and
    analyse in ECMSpy Mono
    ([page 3](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3));
  - **[MegaLogViewer HD](https://www.efianalytics.com/MegaLogViewer/)** (MLV)
    plus a **spreadsheet** (Excel, LibreOffice Calc) and a **map editor**
    (TunerPro RT with the Buell XDF for your ECM, or ECMSpy Mono). MLV needs a
    paid licence for the Histogram/Table Generator; the author considers it
    well worth it. Don't use MLV's *VE Analyze* with its default target AFR
    table: it tries to make closed-loop cells richer than 14.7:1
    ([page 2](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-2)).
- **The same fuel for every ride, the one you normally use.** The thread
  recommends pure gasoline
  ([page 5](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-5)).
  The narrowband sensor switches at λ = 1 with any fuel. But ethanol carries
  oxygen, so with E10 the ECM needs a few percent more fuel to reach λ = 1,
  and the corrections come out a few percent richer than with E0. Tune on the
  fuel you ride on, and don't switch between iterations.

## Process

Keep each iteration together: the image that was in the ECM, the logs recorded
with it, and the result, e.g. `iter0.xpr`, `iter0-ride1.bin`, `iter1.xpr`. The
corrections are only valid for the image the log was recorded with.

### 1. Prepare the ECM

1. **Back up your current tune** (stock or existing) to a file. You need it to
   fall back on and as the base for the first iteration.
2. **Lock the AFV to 100 %.** In EcmDroid's *Setup*:
   - *AFV Settings*: set *AFV (Rear)* and *AFV (Front)* to `100`.
   - *O2 Setup → AFV Settings*: set *Maximum AFV (%)* and
     *Minimum AFV (%)* to `100`, so the ECM can't learn away from it.

   Write down the original values first. You will restore them at the end.
3. **Burn, then *Fetch* the EEPROM again and save it** (e.g. `iter0.xpr`).
   Check that the AFV values are exactly 100 (see
   [known issues](user-guide.md#known-issues)). This saved file is the image
   the log will be compared with.

### 2. Log a ride

1. In EcmDroid's *Log Recorder*, pick a **short interval**: *No Delay* or
   250 ms. Short transients have to be filtered out, and with long intervals
   there's too little data per cell.
2. Warm the engine up fully and ride for about **20 minutes**, covering as many
   RPM and load combinations as you can. Hold each combination steady for a
   few seconds: steady data is the data that gets used. More varied data fills
   more cells. Several rides can be combined.
3. Keep the `.bin` file. For MegaLogViewer, also turn on *Convert to MSL*
   before you stop recording.
4. **Check the log for anomalies before using it.** For example, when you blip
   the throttle on a downshift, the O2 sensors shouldn't max out rich or lean;
   if they do, look at the acceleration enrichment first. Also confirm that the
   AFV stayed at 100 % for the whole ride. If it didn't, step 1 didn't work.
   egotune does both checks for you and lists them in its report.

### 3. Work out the corrections

Use one of the options below. Whichever you choose, only use records where:

- the ECM is in **closed loop** (`Flags2` bit 7, *Closed Loop*);
- the engine is **warm**: at least 71 °C (160 °F) and, *(EcmDroid)*, with no
  warm-up enrichment left (`CrTE`, the `WUE` column in `.msl`, at 100 %).
  Shortly after the engine reaches 71 °C it can still get a few percent of
  warm-up enrichment, and that would make the corrections come out leaner
  than they should;
- *(EcmDroid)* there's **no acceleration or deceleration enrichment**
  (`Flags1` bits 2 and 3, `Accel Corr.` above 0);
- *(EcmDroid)* the engine has been **steady for about a second**. After a
  throttle or RPM change, the O2 signal lags and the EGO correction still
  reflects the previous cell.

Then use only the cells with enough data. A good minimum is **2 seconds of
data** in a cell, which is about 10 records at *No Delay*. Trust cells more
the more data they have.

#### Option A: egotune *(EcmDroid, in testing)*

[egotune](../tools/egotune/README.md) does steps 3 and 4 in one go, for both
cylinders. It applies the filters above, sorts each record into the four cells
around it the way the ECM interpolates, and proposes a new value per cell with
the limits from step 4:

```sh
tools/egotune/egotune.py analyse --image iter0.xpr iter0-ride1.bin
tools/egotune/egotune.py apply --image iter0.xpr iter0-ride1.bin --out iter1.xpr -o iter1.md
```

The report shows, per cylinder, the correction each cell needed, the seconds
of data behind it and the new map, with the changed cells marked. It also
warns when:

- the image doesn't seem to be the one that was in the ECM during the ride;
- the AFV wasn't locked;
- a cell hit the EGO limit;
- the front cylinder has no closed-loop feedback. In that case the front map
  is left as it is.

Read the report before you burn anything, then continue with step 5. In
`iter1.xpr` only the fuel-map bytes differ from `iter0.xpr`;
`calconv diff iter0.xpr iter1.xpr` lists them.

#### Option B: MegaLogViewer and a spreadsheet

1. Open the **Histogram/Table Generator** tab.
2. Set up one view per cylinder and save each one (e.g. *Buell Front Cylinder
   View* and *Buell Rear Cylinder View*):

   | View  | X axis | Y axis | Z axis (TunerPro log) | Z axis (EcmDroid log) |
   |-------|--------|--------|-----------------------|-----------------------|
   | Front | `RPM`  | front load (TunerPro) / `Load1` (EcmDroid) | `EGO Cor2` | `EGO1 Corr.` |
   | Rear  | `RPM`  | rear load (TunerPro) / `Load` (EcmDroid)  | `EGO Cor1` | `EGO Corr.`  |

   The original post uses `TPS 8Bit` as the Y axis for TunerPro logs. On
   DDFI-3 the maps are indexed by load, not by throttle (see
   [above](#what-the-fuel-maps-look-like-ecmdroid)), so use the ADX's load
   column if it has one. Column names in other logs may differ. Check the
   column description if you are unsure which cylinder it belongs to.

   The front view only makes sense if the ECM runs closed loop on the front
   cylinder. That needs a front O2 sensor connected to the ECM and firmware
   that uses it. According to the thread, BUE3D is the only firmware with dual
   O2 sensors enabled by default
   ([page 3](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3)).
   EcmDroid shows the setting as *O2 Setup → Enable Independent Front CL*. If
   the front EGO column doesn't change during the ride, or just repeats the
   rear one, only tune the rear.
3. **Match the table to your fuel maps.** Click the axis-intersection icon and
   type in the X (RPM) and Y (load) breakpoints exactly as they appear in your
   map editor, so every MLV cell lines up with one map cell. Leave out unused
   RPM breakpoints (0).
4. **Colour the table by Hit Weight.** Cells with many samples are the ones you
   can trust. Ignore cells with fewer than about 10 hits at *No Delay*.
5. **Create the data filters** (*Data Filters* icon → new filter). An MLV
   filter **removes** the samples that match its expression:

   | Filter      | Expression (EcmDroid `.msl`) | Removes                                      |
   |-------------|------------------------------|----------------------------------------------|
   | Cold engine | `[CLT_F] < 160`              | samples with the engine below 160 °F (71 °C) |
   | Warm-up     | `[WUE] > 100.5`              | samples with warm-up enrichment *(EcmDroid)* |
   | Enrichment  | `([Flags1] & 12) > 0`        | acceleration/deceleration enrichment *(EcmDroid)* |
   | Open loop   | `[Flags2] < 128`             | open-loop samples                            |
   | Closed loop | `[Flags2] >= 128`            | closed-loop samples                          |

   Bit 7 of `Flags2` is the ECM's closed-loop flag, so a value of 128 or more
   means closed loop. MLV can't skip the second after a transient, so ride
   steadily, or use egotune.
6. **Read the corrections:** select a cylinder view and turn on every filter
   except *closed loop*. What's left is warm, steady, closed-loop data, and
   those are the corrections to use.

MLV puts each sample into the one cell it's nearest to, while the ECM blends
four cells. That's one reason full corrections overshoot (see step 4).

> **About the open-loop step in the original post.** The original post also
> reads open-loop corrections, using the *cold engine* and *closed loop*
> filters. Later in the thread it was shown that the EGO value logged in open
> loop is just the last closed-loop correction, frozen (see
> [above](#what-a-narrowband-sensor-can-and-cant-tell-you)). Those numbers
> aren't real corrections, so don't apply them. In EcmDroid's `.msl` files the
> `Gego`/`Gego1` columns already account for this: they show the EGO
> correction in closed loop and the AFV in open loop
> ([details](logging.md#how-the-converter-works)).

### 4. Apply the corrections

egotune (option A) does this step for you, with the limits below. By hand,
lay out one sheet per cylinder (or side by side) with three blocks of the same
size as the fuel map:

1. **Original map:** paste the current fuel map from your map editor.
2. **Corrections:** paste the EGO correction table from MLV. Leave empty the
   cells you don't trust (no data, or too few hits).
3. **Result:** each cell multiplies the original by the correction, and keeps
   the original value where the correction is empty. For example, if the
   original map starts at `B2` and the corrections at `B22`:

   ```
   =IF(ISBLANK(B22), B2, ROUND(B2 * B22 / 100, 0))
   ```

   Round to whatever resolution your map editor shows.

**Apply only part of each correction.** The ECM interpolates between cells, so
changing one cell also affects its neighbours, and full corrections start to
overshoot: the next log then shows the opposite correction, and you end up
chasing your own tail. One thread member applies only a third of the
correction each time and stops once the changes are minimal or keep going back
and forth
([page 3](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3)).
With a factor of one third, the formula becomes:

```
=IF(ISBLANK(B22), B2, ROUND(B2 * (1 + (B22 / 100 - 1) / 3), 0))
```

**Limit each step, and take fuel away more carefully than you add it**
*(EcmDroid)*. A lean mistake is the dangerous one, and there's no knock
sensor. egotune's defaults are at most +6 % and −3 % per cell per iteration.
Also keep in mind that the map's resolution is coarse: a cell of 30 can only
move in steps of about 3 %, so a small correction may round away. That's fine.

Then:

1. **Paste the result maps back** into TunerPro (or your map editor). TunerPro
   highlights the changed cells in red.
2. **Sanity-check the changes.** Save the file, reopen it in TunerPro and
   compare it with the original. The comparison view shows how much each cell
   moved, and you can 3D-graph both the maps and the difference to see where
   the adjustments were made. Large or isolated jumps usually point to bad
   data, not a bad map.

### 5. Burn and iterate

Burn the new maps to the ECM, *Fetch* and save the image again (e.g.
`iter1.xpr`), then either:

- **keep the AFV locked at 100 %** and repeat steps 2–5 to refine further, or
- **restore the original AFV limits** (step 1) so the ECM can adapt
  dynamically again, for a final tune.

Several iterations usually give the best result. **Stop** when every cell with
enough data stays within about **±2 %**, or when cells keep going back and
forth between iterations. egotune's report says when the cells it can see are
within ±2 %.

## After tuning

Ride the "final" tune for a while, then check the learned AFV now and then
(EcmDroid's *Data Channels* screen shows it). If the maps are good, it should
stay **close to 100 %**. If it drifts far from 100 %, the maps still need work.
As the ECMSpy author puts it in the thread, there's no need to chase exact
numbers: "once the AFV is stable, CL is set up correctly"
([page 3](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3)).

According to the author of the method, several successful iterations give you
an engine that:

- runs smoothly and as efficiently as possible at all RPMs and loads;
- doesn't overheat or run too cold at any point;
- idles steadily;
- sounds great throughout the RPM range;
- has no flat spots, with strong power everywhere.

Every engine is a little different, which is why fine-tuning the factory maps
to your engine pays off.

## Going further

**Tune closed loop first.** Both the ECMSpy author and the author of the
method stress this. If the closed-loop cells are off, the AFV learns a
correction there and applies it in open loop too, which ruins any open-loop or
WOT tuning
([page 5](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-5)).

**Open loop and WOT need a wideband sensor**, ideally with a dyno. A wideband
doesn't help with closed loop, where the mixture is stoichiometric anyway
([page 3](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-3)).
Notes from the thread:

- If the wideband controller also feeds the ECM through a simulated narrowband
  output, choose one that works with the ECM's low input impedance. The
  Innovate LC-1 is reported to give wrong readings; Tech-Edge and the PLX
  SM-AFR are reported to work
  ([page 1](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/),
  [page 2](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-2),
  [page 4](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-4)).
- Otherwise keep the stock narrowband sensors connected to the ECM and use the
  wideband for logging only.
- For reference, the author of the method ended up with these WOT targets after
  several wideband iterations: 13.2:1 at TPS 255, 13.7:1 at 175,
  14.0:1 at 125 and 14.3:1 at 100 (8-bit TPS)
  ([page 5](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/page-5)).
- Don't lean out the open-loop or WOT cells to chase power. Extra fuel cools
  the combustion chamber, and there's no knock sensor to protect the engine.

Narrowband tuning is still an accessible way to get started for any rider who
is comfortable with a computer, without booking dyno time.

See also the [ecmspy.com Tuning Guide](https://ecmspy.com/tgv2/guide2.shtml)
and the ECMSpy Mono user guide pages on
[O2 setup](https://ecmspy.com/ug_mono/V2.0/o2setup.shtml) and
[corrections](https://ecmspy.com/ug_mono/V2.0/corrections.shtml#open-loop).
