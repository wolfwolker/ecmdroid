# How to Tune the Fuel Maps with egotune

This guide is for riders who want to fine-tune the closed-loop fuel maps of a
DDFI-3 Buell (XB 2008+, 1125R/CR) with the stock narrowband O2 sensors. It uses
`egotune`, an offline tool in this repository: you record a ride with EcmDroid,
and egotune turns the log into corrected front and rear fuel maps in a new
`.xpr`. The technical reference is [tools/egotune/README.md](../tools/egotune/README.md).

The method comes from the post "OE Narrowband Tuning" in the BuellXB.com
thread
[*DDFI-3 tuning with stock O2 sensor*](https://www.buellxb.com/threads/ddfi-3-tuning-with-stock-o2-sensor.52841/post-599001):
lock the AFV, log, apply part of the corrections, and iterate. egotune does the
analysis that the post does with MegaLogViewer and a spreadsheet.

> **Status (October 2026): in testing.** egotune checks its own result, but
> no map it made has been burned and ridden yet, and its lookup check hasn't
> been confirmed on a log and the image it was recorded with. Read every report
> before you burn anything, and keep your original image.

> **Warning:** burning the EEPROM changes how your engine runs. A wrong value
> can make the engine run lean, overheat or get damaged. Buells have no knock
> sensor, so a lean mixture under load isn't caught by the ECM.

## How it works

In closed loop the ECM trims fuel with the **EGO correction** (short-term O2
feedback) and learns a long-term **AFV** per cylinder. Both are percentages
where 100 % means "no correction". With the AFV locked at 100 %, every error in
the map shows up in the EGO correction: a cell where the ECM kept adding 6 %
fuel is 6 % lean. egotune averages that correction per map cell and moves each
cell part of the way.

## What it does and doesn't do

- It **reads** your `.xpr` and one or more `.bin` logs, and **writes** a new
  `.xpr`. It never talks to the ECM. You burn the result with EcmDroid, as
  usual.
- It changes **only the fuel maps** `Tab_Fuel_Front` and `Tab_Fuel_Rear`.
  Every other byte stays the same, and it checks that.
- It only uses **warm, steady, closed-loop** data: no warm-up, acceleration or
  deceleration enrichment, and not in the second after a throttle or RPM
  change.
- It only changes cells with **enough data**: at least 2 seconds.
- It changes each cell **a little per round**: a third of the correction, at
  most +6 % or −3 %. So expect a few rounds.
- It tunes the **front map only if the ECM runs closed loop on the front
  cylinder**. That needs a front O2 sensor and firmware that uses it (BUE3D, or
  *O2 Setup → Enable Independent Front CL*). Otherwise it leaves the front map
  alone and says why.
- It **can't** tune open loop or WOT: a narrowband sensor has nothing to say
  there. Those need a wideband sensor.
- It only supports **DDFI-3** ECMs.

## What you need

- EcmDroid and a [supported adapter](user-guide.md#what-you-need).
- A PC with Python 3.11 or newer (or [pkgx](https://pkgx.sh)), and a copy of
  this repository. egotune uses `tools/calconv` too, so keep the two folders
  side by side.
- **The same fuel for every ride**, the one you normally use. Ethanol makes the
  corrections come out a few percent richer, so don't switch between rounds.

Keep each round's files together and name them so you can tell them apart,
e.g. `iter0.xpr`, `iter0-ride1.bin`, `iter1.xpr`, `iter1.md`. A log only fits
the image that was in the ECM while it was recorded.

## Steps

### 1. Prepare the ECM

1. **Save your current tune** (*Fetch*, then save the `.xpr`). It's your way
   back.
2. **Lock the AFV at 100 %** in EcmDroid's *Setup*:
   - *AFV Settings*: *AFV (Rear)* and *AFV (Front)* to `100`;
   - *O2 Setup → AFV Settings*: *Maximum AFV (%)* and *Minimum AFV (%)* to
     `100`.

   Write down the original values. You restore them at the end.
3. **Burn, *Fetch* again and save** the image as `iter0.xpr`. Check that the
   AFV values are exactly 100 (see [known issues](user-guide.md#known-issues)).

### 2. Record a ride

1. In the *Log Recorder*, choose the interval *No Delay* or *250 ms*.
2. Warm the engine up fully, then ride for about 20 minutes. Cover as many RPM
   and throttle combinations as you can, and hold each one steady for a few
   seconds: steady data is what gets used.
3. Copy the `.bin` file to your PC, e.g. as `iter0-ride1.bin`. You can record
   several rides and use them together.

### 3. Look at the corrections

```sh
tools/egotune/egotune.py analyse --image iter0.xpr iter0-ride1.bin
```

This writes nothing. Read the report (see [Reading the report](#reading-the-report)).
If it has warnings, sort them out first.

### 4. Make the new image

```sh
tools/egotune/egotune.py apply --image iter0.xpr iter0-ride1.bin --out iter1.xpr -o iter1.md
```

`iter1.md` is the report. Check the new map grids: large or isolated changes
usually mean bad data, not a bad map. `calconv diff iter0.xpr iter1.xpr` lists
exactly what changed.

### 5. Burn and repeat

Burn `iter1.xpr` with EcmDroid, *Fetch* and save it again, ride, and run
egotune on the new image and the new log. Stop when the report says every
cell with enough data is within ±2 %, or when cells keep going back and forth
between rounds.

### 6. Finish

Restore the original AFV limits (step 1) so the ECM can adapt again. Ride for a
while and check the learned AFV now and then (*Data Channels*). If the maps are
good, it stays close to 100 %.

## Reading the report

The top lists the files, how many records were used, and why the others were
left out. Then, per cylinder:

- **Correction the ECM needed**: the mean correction per cell, in %. A
  positive value means the cell is lean and gets more fuel. Values in
  *italics* have less than 2 s of data and aren't used. `!` marks a cell where
  the EGO correction sat at its limit: the real error is bigger than shown.
- **Data**: the seconds of data per cell.
- **New map**: the map after this round. Changed cells show **new** (old).

Warnings and what to do about them:

| Warning | What to do |
|---|---|
| The image stores a different AFV than the log shows, or the lookup check has a large spread | You probably used the wrong image. Use the one you saved right after the last burn. |
| The AFV wasn't locked | egotune takes it into account, but lock it (step 1) for cleaner data. |
| The image's AFV limits aren't locked at 100 % | Same as above. |
| Front map left unchanged | Your ECM has no front closed loop. Only the rear map is tuned. |
| No record passed the filters | The engine wasn't warm, or never steady in closed loop. Ride longer after a full warm-up. |

## Settings

The defaults follow the method. Change them only if you know why:

| Option | Default | What it does |
|---|---|---|
| `--gain` | 0.33 | part of each correction applied per round |
| `--max-rich`, `--max-lean` | 6, 3 | most a cell may gain or lose per round, in % |
| `--min-seconds` | 2 | data a cell needs before it's changed |
| `--full-seconds` | 10 | data at which a cell gets the full gain |
| `--min-te` | 71 | warm engine from, in °C |
| `--settle` | 1 | seconds skipped after a throttle or RPM change |
| `--cylinders` | both | `front` or `rear` to tune just one map |

Raising the caps makes each round bigger, and a lean mistake is the dangerous
one.
