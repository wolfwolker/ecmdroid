# User Guide

EcmDroid turns an Android phone or tablet into a diagnostic and configuration
tool for Buell motorcycles with DDFI, DDFI-2 and DDFI-3 ECMs (fuel-injected
tube-frame models, XB models and 1125R/CR). It reads and clears trouble codes, runs actuator tests,
shows and records live data, and reads, edits and writes the ECM's EEPROM.

> **Warning:** writing ("burning") the EEPROM changes how your engine runs.
> A wrong value can make the bike run badly or not start, and can damage the
> engine. Always save a backup of the original EEPROM (`.xpr`) before you
> change anything. EEPROM burning is off by default and you have to turn it on
> in Settings.

## What you need

- Android 8.0 or newer. APKs are published on
  [GitHub Releases](https://github.com/ecmdroid/ecmdroid/releases).
- An adapter between the phone and the bike's diagnostic connector:
  - **Classic Bluetooth serial adapter (SPP)**: pair it first in Android
    *Settings → Bluetooth*. ecmspy.com explains how to
    [build one](https://ecmspy.com/btwireless2.shtml). Pre-built adapters are
    also sold, e.g. by [buell-parts.com](https://buell-parts.com/Bluetooth-Adapter-Version-2).
  - **Bluetooth LE serial adapter**: no pairing. EcmDroid scans for it. Supported
    module families: TI CC254x (HM-10 style), Nordic nRF51822 (nRF UART),
    Microchip RN4870/1, Telit Bluemod (TIO).
  - **USB-to-serial adapter** with TTL levels (FTDI, CP210x, PL2303, CH34x,
    CDC) through a USB-OTG cable. ecmspy.com describes a
    [PC cable](https://ecmspy.com/kabel_pc.shtml) built from an FTDI USB-to-TTL
    cable and the matching diagnostic plug, and has the connector
    [pinouts](https://ecmspy.com/pinouts.shtml).
  - **TCP/IP** to a WiFi-to-serial bridge or the [ecmsim](https://github.com/ecmdroid/ecmsim)
    simulator.
- The diagnostic connector is under the seat on XB-9/12 "S" models and behind
  the front mask on XB-9/12 "R" models.

> **Hardware note:** the ECM's diagnostic line uses TTL levels and must never
> see more than 5 V (ecmspy.com). Don't connect an RS-232-level serial port
> directly.

### Serial settings and ECM protocol

| ECM                                   | Protocol in EcmDroid | Adapter speed  |
|---------------------------------------|----------------------|----------------|
| Stock (street) and **P&A race** ECMs  | *Stock / P&A*        | 9600 baud, 8N1, no handshake  |
| **Factory Race** ECMs                 | *Factory Race*       | 19200 baud, 8N1, no handshake |

Most ECMs are stock or P&A. P&A race ECMs usually have a *printed* "RACE USE
ONLY" marking. Factory Race ECMs usually have an *engraved* one.

Bluetooth adapters must be configured for the right speed beforehand. USB
adapters are set up by EcmDroid automatically.

## First steps

1. Open **Settings** (navigation drawer) and choose the **ECM Connection** type.
   For TCP/IP, also enter host and port.
2. Set a **Log Storage Location** if you want to record logs.
3. On **ECM Information**, pick the **Protocol** (Stock / P&A or Factory Race).
   You can only change it while disconnected.
4. Turn on the ignition and tap the round **connect button** (red =
   disconnected, grey = connecting, green = connected):
   - Classic Bluetooth: pick the paired adapter from the list.
   - Bluetooth LE: a scan screen opens. Tap your adapter.
   - USB: the first USB serial adapter is used. The first time, Android asks for
     permission. Grant it and tap connect again.
5. EcmDroid identifies the ECM and reads the **whole EEPROM**. This takes a
   while. The ECM Information screen then shows ID, version, type, serial
   number, manufacturing date, layout revision, country ID and calibration ID.

If the ECM ID isn't in EcmDroid's database, the connection ends with
*"Unsupported ECM Version"*. See [supported-ecms.md](supported-ecms.md).

## Screens

### Trouble Codes

*Read Errors* shows **Current Errors** and **Stored Errors**, each with its
numeric trouble code and description. *Clear Errors* asks for confirmation
("OK to permanently clear all errors?") and then tells the ECM to clear its
codes.

Without a connection, stored codes are read from the currently loaded EEPROM
image, if there is one.

### Active Tests

Pick a component under *Choose Device Test* and tap *Start* to make the ECM
run it: front/rear coil,
tachometer, fuel pump, front/rear injector, fan, exhaust valve, active intake,
shift light. The app waits until the ECM reports that the test has finished.

**TPS Reset** (DDFI and DDFI-2 only) follows these on-screen steps: back out the
idle adjuster, snap the throttle open and shut 2–3 times, make sure the throttle
plate is fully closed, press *OK*, then open the throttle 5–6° and set idle to
1050–1100 rpm. On DDFI-3 ECMs, follow the service manual instead.

### Data Channels

Shows five live values at once. Use each row's selector to pick a value (scalar
values show a bar, bitfields show eight check boxes). The *Live Data On/Off*
button starts and stops live updates. You can't change channels while live data
is on. Your selection is remembered. The defaults are battery
voltage, RPM, throttle position (degrees), AFV and engine temperature.

### Setup

A structured editor for common ECM parameters, grouped as:

- **General Config:** system options (bank angle sensor, deceleration fuel cut,
  idle fuel/ignition adjust, …), noise-reduction options, airbox pressure / baro
  sensor configuration, shifter and shift light
- **Error Mask:** which sensor and actuator faults the ECM reports. **Checked
  means the error is active:** the ECM signals and stores it. **Unchecked masks it**, so the ECM ignores that fault. The
  database describes it like this: "Every mask bit not set will prevent the
  corresponding error from being signaled or stored." An entry whose bits are
  partly set and partly cleared isn't shown.
- **Limits:** RPM limits (normal and cold engine), temperature limits, fan setup
  (key-on and key-off)
- **AFV Settings:** rear and front AFV (front on DDFI-3 only)
- **O2 Setup:** O2 sensor thresholds, closed-loop configuration, EGO correction
  and AFV learning limits
- **Exhaust Config:** exhaust valve (AMC) configuration

Entries your ECM doesn't have are greyed out. With *Settings → Hide EEPROM
variables* they're hidden. Changes only touch the local
copy until you tap **Apply Changes**, which burns them to the ECM (this
requires *Enable EEPROM burning*).

### Log Recorder

Records live data to a file in your log storage location:

1. Pick a *Log Interval* (*No Delay*, 250 ms … 5 s) and optionally turn on
   *Convert to MSL*.
2. Tap *Start Recording*. A notification stays up while recording. The screen
   shows records/kilobytes and live TPS, RPM and engine temperature.
3. Tap *Stop recording*. If *Convert to MSL* is on, a `.msl` file is created
   next to the `.bin` file, ready for MegaLogViewer.

Files are named after the start time, e.g. `20260412_181502.bin`. Turn on
*Settings → Keep Screen On* for long sessions. The formats are described in
[logging.md](logging.md).

### EEPROM

A hex view of the whole EEPROM image, with each byte colour-coded by value. Tap
a byte to see its offset, value, both 16-bit interpretations, and which ECM
variable it belongs to. **Long-press** a byte to edit it.

Menu:

- **Fetch:** read the EEPROM from the ECM again. You're warned if this would
  overwrite unsaved local changes.
- **Burn:** write the image to the ECM. Requires *Enable EEPROM burning*. The
  connected ECM must have the same ECM ID as the image. With *Optimized
  Burning*, only changed pages are written.
- **Save:** store the image as `<ECM-ID>_<date>-<time>.xpr`.
- **Load:** open an `.xpr` (or legacy `.epr`) file. The ECM type is detected
  from the file size. If several types match, you choose one.

### Torque Values

A reference list of fastener torque values for Buell XB models.

## Settings

| Setting                              | Effect                                                     |
|--------------------------------------|------------------------------------------------------------|
| Log Storage Location                 | Folder for recorded logs                                   |
| ECM Connection                       | Classic Bluetooth, Bluetooth LE, TCP/IP, USB-to-serial     |
| TCP/IP host / port                   | Target for TCP/IP connections (default 192.168.1.1:6275)   |
| Hide EEPROM variables                | Hide Setup entries your ECM doesn't have                   |
| Enable EEPROM burning                | Allows writing to the ECM. *Use at your own risk!*         |
| Optimized Burning                    | Write back only modified pages                             |
| Keep Screen On                       | Keep the display on while recording                        |

## Known issues

These are open issues in the current version. Until they're fixed, keep them
in mind when changing ECM settings:

- **Typed values can be stored slightly lower.** A value like 101.3 % can end
  up burned as 101.2 %. After burning, *Fetch* the EEPROM again and check the
  values that matter.
- **Out-of-range values aren't rejected.** A number too large for the setting
  wraps around (e.g. 300 in a 1-byte setting becomes 44). Only enter values
  within the setting's normal range.
- **Hex edits in page 0 aren't burned.** Page 0 is the last few bytes of the
  EEPROM view. Only the Front AFV and Baro values there are written to the ECM;
  other edits in that area are ignored even though the burn reports success.
- **`.epr` files can't be burned** to ECMs that have a page 0 (DDFI-2 BUEGB/IB/IC
  and B2RIB, all DDFI-3). Use `.xpr` files.
- **The Factory Race protocol setting may reset to Stock / P&A after restarting
  the app.** Check it before connecting.
- **MSL conversion isn't available** for BUEIA, BUEGC and B3R2D logs. The
  `.bin` file is still recorded.
- **Long recordings with the app in the background may stop.** Keep EcmDroid in
  the foreground (*Keep Screen On* helps).
- **A lost connection isn't shown.** If the link drops (engine off, out of
  Bluetooth range), the connect button and *Live Data* stay on, and the values
  freeze. Frozen values mean the link is gone: disconnect and connect again.

## Troubleshooting

| Symptom                                               | Things to check                                                                                  |
|-------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| "No valid response from ECM (wrong Protocol?)"        | Protocol setting (Stock/P&A vs Factory Race) and adapter baud rate (9600 vs 19200).              |
| Timeouts / "Timeout reading …"                        | Ignition on? Adapter powered and wired correctly? Bluetooth range?                               |
| "Unsupported ECM Version"                             | Your ECM ID isn't in the bundled database.                                                       |
| No paired devices listed                              | Pair the adapter in Android settings first. On Android 12+ grant the *Nearby devices* permission. |
| "Give USB Permission and try again."                  | Accept the USB permission dialog, then tap connect again.                                         |
| "Please configure log storage location first"         | Set *Log Storage Location* in Settings.                                                          |
| "EEPROM burning disabled by configuration."           | Turn on *Enable EEPROM burning* in Settings.                                                     |
| "Incompatible ECM version. Please disconnect first."  | The loaded file is for a different ECM ID than the connected ECM.                                 |
