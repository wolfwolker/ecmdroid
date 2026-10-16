# Supported ECMs

EcmDroid supports exactly the ECM IDs in its bundled database. After
connecting, it reads the ECM version string (e.g. `BUEIB310 12-11-03`). The
**first five characters** are the ECM ID, and the ID selects the EEPROM layout,
runtime data layout and all variable definitions.

## ECM families

| `ECM.Type` | Family | Motorcycles                                                                 |
|------------|--------|-----------------------------------------------------------------------------|
| `DDFI1`    | DDFI   | fuel-injected tube-frame models ("Tubers", e.g. X1 Lightning, S3 Thunderbolt), 1999–2002 |
| `DDFI2`    | DDFI-2 | XB models 2003–2007                                                         |
| `DDFI3`    | DDFI-3 | XB models 2008 and later, 1125R/CR                                          |

## Supported ECM IDs

The model years come from ecmspy.com's
[supported ECM list](https://ecmspy.com/supported.shtml). Everything else
comes from EcmDroid's bundled database.

| ECM ID | Type   | Motorcycles (ecmspy.com)                 | Layout (category) | `.epr` / `.xpr` size (bytes) | Runtime frame |
|--------|--------|------------------------------------------|------------------:|------------------------------|--------------:|
| BUEIA  | DDFI   | Tube frame, 1999–2002                    | 3                 | 1056 / 1056                  | 100           |
| BUEGC  | DDFI   | Tube frame, 1999–2002                    | 4                 | 1100 / 1100                  | 99            |
| BUEJA  | DDFI   | Tube frame, 1999–2002                    | 5                 | 1072 / 1072                  | 99            |
| BUEKA  | DDFI   | Tube frame, 1999–2002                    | 5                 | 1072 / 1072                  | 99            |
| BUECB  | DDFI-2 | XB9, 2003                                | 6                 | 1138 / 1138                  | 103           |
| BUEGB  | DDFI-2 | XB, 2004                                 | 7                 | 1198 / 1202                  | 107           |
| BUEIB  | DDFI-2 | XB, 2005–2007                            | 8                 | 1206 / 1210                  | 107           |
| BUEIC  | DDFI-2 | XB, 2005–2007 (Japan only)               | 8                 | 1206 / 1210                  | 107           |
| B2RIB  | DDFI-2 | XB, 2005–2007 (Factory Race ECM)         | 9                 | 1206 / 1210                  | 107           |
| BUEOD  | DDFI-3 | XB, 2008 and later                       | 79                | 2788 / 2820                  | 135           |
| BUEWD  | DDFI-3 | XB, 1125, 2008 and later                 | 88                | 3116 / 3156                  | 135           |
| BUEYD  | DDFI-3 | XB, 1125, 2008 and later                 | 89                | 3232 / 3272¹                 | 135           |
| BUEZD  | DDFI-3 | XB, 1125, 2008 and later                 | 90                | 3372 / 3412                  | 135           |
| BUE1D  | DDFI-3 | XB, 1125, 2008 and later                 | 49                | 3404 / 3444                  | 135           |
| B3R1D  | DDFI-3 | XB, 1125, 2008 and later (EBR Race ECM)  | 49                | 3404 / 3444                  | 135           |
| BUE2D  | DDFI-3 | XB, 1125, 2008 and later                 | 50                | 3756 / 3796                  | 135           |
| B3R2D  | DDFI-3 | EBR Race ECM (DB remark; not on the ecmspy.com list) | 50    | 3756 / 3796                  | 135           |
| BUE3D  | DDFI-3 | XB, 1125, 2008 and later                 | 51                | 3884 / 3924                  | 135           |
| B3R3D  | DDFI-3 | XB, 1125, 2008 and later (EBR Race ECM)  | 51                | 3884 / 3924                  | 135           |

- **`.epr` size** = EEPROM without page 0 (`eeprom.size`). **`.xpr` size** =
  with page 0 (`eeprom.xsize`). They're equal for layouts without page 0. These
  sizes are how EcmDroid detects the ECM type when loading a file (see
  [eeprom.md](eeprom.md#eeprom-files-xpr)).
- IDs in the same layout category share every offset definition. Per-layout
  statistics are in [database.md](database.md#database-coverage).

¹ ecmspy.com lists 3250 bytes as the BUEYD `.xpr` size. That's a typo: EcmDroid's
database (page 0 = 40 bytes) and real BUEYD images read from ECMs are 3272 bytes.

### Reading an ECM ID

The ecmspy.com [Tuning Guide](https://ecmspy.com/tgv2/guide2.shtml) ("Buell ECM
History") explains the naming. The full version string is e.g.
`BUEIB310 12-11-03`, and EcmDroid only uses the first five characters:

- `BUE` = Buell street ECM. `B2R` = DDFI-2 Factory Race ECM. `B3R` = DDFI-3
  (EBR) race ECM.
- The **two characters after the prefix** (`KA`, `IB`, `2D`, …) identify the
  type:
  - Second character: `A` = DDFI (tube frame), `B` = DDFI-2, `C` = Japan-only
    variant, `D` = DDFI-3.
  - The first character usually changes with the EEPROM layout.

The database is still the single source of truth. For example, BUEGC is listed
there as a DDFI (tube frame) ECM even though its second character is `C`.
Race and street ECMs with the same suffix (`B3R1D`/`BUE1D` etc.) share one
layout.

## DDFI-3: firmware, calibration and swapping ECMs

This section collects community knowledge about 2008–2010 DDFI-3 ECMs. It's
useful when you replace an ECM, swap one between models, or upgrade firmware.
It isn't EcmDroid behaviour. Sources are listed at the end, and the claims are
only as reliable as those sources.

### Firmware and calibration are different things

- **Firmware** is the ECM's program. It determines the **ECM ID**
  (BUEYD, BUE2D, …) that the version request reports, and the EEPROM
  layout. EcmDroid, EcmSpy and TunerPro **can't change firmware**. They talk
  through the diagnostic port and only read and write the EEPROM.
- **Calibration** is the EEPROM content (the `.xpr` image): maps, settings,
  limits and configuration. It's what makes an ECM run a particular model.
  Layouts that have them identify the calibration with `Cal_ID` and
  `KID_Series`/`KID_Market`/`KID_Version`. These appear as *Calibration ID* and
  *Country ID* on the ECM Information screen.
- **A calibration only fits its own firmware.** "Any BUE2D calibration can be
  flashed onto any BUE2D ECM, the same goes for BUEYD, BUEZD, etc." (buellxb.com).
  Images for different firmware aren't interchangeable. For example, BUEYD is
  3272 bytes and BUE2D is 3796 bytes, and 485 of the 527 variables they share
  sit at different offsets. EcmDroid refuses such files: the size → ID detection
  and the burn's ID check both reject them. Individual settings can be
  re-entered or moved over by variable name, but you can't copy the file.

### One ECM hardware for XB and 1125

- ecmspy.com's [pinout page](https://ecmspy.com/pinouts.shtml) states that
  DDFI-3 ECMs for the XB (Thunderstorm) engine "use the same ECM hardware as the
  Helicon engines [1125], and require the same plugs" (two 34-pin AMP Superseal
  sockets).
- The firmware types BUEWD, BUEYD, BUEZD, BUE1D, BUE2D and BUE3D are listed for
  both XB and 1125. BUEOD is listed for XB only.
- Aftermarket tunable DDFI-3 ECMs are sold for "all 2008-2010 Buell™
  motorcycles including the 1125R, 1125CR, XB9, and XB12", with the
  calibration chosen per model.

The two harnesses use different pins. That's why the calibration must match the
motorcycle:

| Function            | 1125 (Helicon)                       | XB (Thunderstorm)                                              |
|---------------------|--------------------------------------|----------------------------------------------------------------|
| Instrument cluster  | CAN bus (grey 29/30)                 | discrete tachometer, check-engine lamp and speed outputs (black 21–23) |
| Engine temperature  | coolant sensor (grey 9)              | head temperature sensor (grey 11)                              |
| Pressure sensors    | MAP, baro, fuel pressure (grey 5/6/10) | none                                                         |
| Exhaust valve (AMC) | –                                    | control (black 1), feedback (grey 9)                           |
| Cooling fans        | two                                  | one                                                            |

### Using an 1125 ECM in an XB (or the reverse)

This should work, **after the ECM gets a calibration for the target
motorcycle**. Asked whether an 1125R ECM needs reflashing for an XB12, the
answer on buellxb.com was "Yes it does". With the original calibration it would
run the wrong engine's maps and expect the wrong sensors and outputs.

1. Read the donor ECM's ID (e.g. BUE2D) and save its `.xpr` as a backup.
2. Get a stock calibration **for the target model and the same ECM ID**, e.g.
   from the original ECM of the target bike if its ID matches, from a dealer
   flash, or from a tuner.
3. Burn it. EcmDroid allows this because the IDs match. An `.xpr` burn writes
   pages 1…n as raw bytes.
4. Do the TPS reset (service manual procedure on DDFI-3). Then check trouble
   codes, and use the active tests to check the tachometer, fan, exhaust valve
   and so on.

**Open question:** EcmDroid doesn't overwrite page 0 (see
[eeprom.md](eeprom.md#burning-writing-back)), so the donor's VIN, odometer and
security data (`KVIN`, `Odo`, `Sec_PIN`) stay in the ECM. No reliable source was
found on whether donor security settings can block starting on the other
motorcycle. Check this before relying on such a swap.

### Upgrading firmware (e.g. BUEYD → BUE2D)

- Firmware is upgraded with the dealer tool (Harley-Davidson/Buell *Digital
  Technician*). Community sources describe the path BUEYD (original) → BUEZD →
  BUE2D, with BUE2D as the last version dealers offered.
  [Revision Moto](https://www.rev-mo.com/ecmbasics) quotes "$40 - $50" and "less
  than 30 minutes", and recommends it for 2008+ bikes without BUE2D. Whether
  dealers can still do this today wasn't verified.
- The dealer installs firmware **and** a stock calibration. Your previous
  `.xpr` won't load afterwards, so save it first and note your custom settings
  to re-enter them.
- Flashing firmware without the dealer tool isn't possible with EcmDroid and
  isn't planned. Community posts
  mention unreleased attempts, but no public tool or protocol description was
  found.
- The alternative is an ECM that already runs the wanted firmware (used, or an
  aftermarket tunable ECM).
- In EcmDroid's database, BUE2D (compared with BUEYD) adds a separate rev
  limiter for neutral/clutch (`KNCRPM_*`), speed-based fan tables
  (`Tab_VS_Fan_On/Off`), a front idle spark table, timing table configuration
  bits (`KSpark_Config`) and calibration ID fields. One forum user reported AFV
  resetting on every key cycle with BUEZD.

Sources:
[ecmspy.com pinouts](https://ecmspy.com/pinouts.shtml) ·
[ecmspy.com supported ECMs](https://ecmspy.com/supported.shtml) ·
[buellxb.com: 1125R/XB12 ECM reflash](https://www.buellxb.com/threads/1125r-xb12-ecm-oem-reflash.42857/) ·
[buellxb.com: firmware flash](https://www.buellxb.com/threads/firmware-flash-in-tucson.53508/) ·
[Revision Moto: ECM basics](https://www.rev-mo.com/ecmbasics) ·
[IDS: DDFI-3 tuning package](https://idspd.com/xcart/2008-2010-buell-tunable.html)

## Stock, P&A race and Factory Race ECMs

Before connecting, you choose the protocol in EcmDroid. It decides the serial
speed and the ECM's bus address:

| Kind                                  | Choose         | Baud  | Address |
|---------------------------------------|----------------|-------|---------|
| Stock street ECM                      | Stock / P&A    | 9600  | `0x42`  |
| P&A (Parts & Accessories) race ECM    | Stock / P&A    | 9600  | `0x42`  |
| Factory Race ECM                      | Factory Race   | 19200 | `0x55`  |

P&A race ECMs usually have a *printed* "RACE USE ONLY" marking on the casing.
Factory race ECMs usually have an *engraved* one.

## Feature availability by family

| Feature                                  | DDFI | DDFI-2 | DDFI-3 |
|------------------------------------------|:----:|:------:|:------:|
| Read version / EEPROM, live data, logs   | ✓    | ✓      | ✓      |
| Trouble codes (current / stored)         | ✓    | ✓      | ✓      |
| Active tests                             | ✓¹   | ✓¹     | ✓¹     |
| TPS reset from the app                   | ✓    | ✓      | – (service manual procedure) |
| EEPROM page 0                            | –    | GB/IB/IC/B2RIB only (4 bytes) | ✓ (32–40 bytes) |
| Front AFV (`LFuel1`) editable            | –    | –      | ✓ (not BUEOD, see [eeprom.md](eeprom.md#burning-writing-back)) |
| MSL log conversion                       | BUEJA, BUEKA only | ✓ | ✓ except B3R2D |

¹ Every ECM gets the same test list. Whether a test does anything depends on
the motorcycle having that actuator (e.g. exhaust valve, active intake).

## Unsupported ECMs

If the connected ECM's ID isn't in the table, the connection fails with
*"Unsupported ECM Version '…'"*. Supporting a new ID means adding its
definitions to the database. See
[development.md](development.md#supporting-a-new-ecm-version).
