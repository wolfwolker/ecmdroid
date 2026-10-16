# EcmDroid

EcmDroid is an Android application to diagnose and configure Buell motorcycles
with a DDFI, DDFI-2 or DDFI-3 ECM: fuel-injected tube-frame models, the XB
range and the 1125R/CR. It's heavily based on the work of the
[ecmspy.com](https://ecmspy.com) project, whose protocol documentation and ECM
database it uses.

- **Trouble codes:** read current and stored codes, clear them
- **Active tests:** coils, injectors, fuel pump, fan, tachometer, exhaust
  valve, active intake, shift light, and TPS reset (DDFI/DDFI-2)
- **Live data:** five configurable channels from the ECM's runtime data
- **Log recorder:** binary logs with optional conversion to MegaLogViewer
  `.msl`
- **Setup:** edit ECM parameters (system config, error mask, RPM and
  temperature limits, fan, AFV, O2/closed loop, exhaust valve)
- **EEPROM:** fetch, hex-edit, burn, and load/save ECMSpy-compatible `.xpr`
  images

APKs are published on [GitHub Releases](https://github.com/ecmdroid/ecmdroid/releases).
Android 8.0 or newer is required.

> **Warning:** burning the EEPROM changes how your engine runs. Keep a backup
> of the original EEPROM. Burning is off by default (*Settings → Enable EEPROM
> burning*). Use at your own risk.

## Connecting to the motorcycle

Communication with the ECM goes through a **Bluetooth**, **Bluetooth LE**
or **USB-to-serial** adapter connected to the motorcycle's diagnostic plug, or
through **TCP/IP** to a WiFi bridge or the simulator. The plug is located
underneath the seat (on XB-9/12 "S" models) or behind the front mask (on
XB-9/12 "R" models).

This [article](https://ecmspy.com/btwireless2.shtml) explains how to build a
Bluetooth serial adapter. Pre-built adapters are also offered by various
vendors, e.g. [buell-parts.com](https://buell-parts.com/Bluetooth-Adapter-Version-2).

Initial pairing of your Android device and a classic Bluetooth serial adapter
must be done in the Android Settings application. Pairing is not required for
BLE serial adapters. Also:

- For **Standard and P&A ECMs**, set the adapter to **9600, 8N1, no
  handshake**. This will be the vast majority of ECMs.
- For **Factory Race ECMs**, set the adapter to **19200, 8N1, no handshake**,
  and select the *Factory Race* protocol on EcmDroid's ECM Information screen.

P&A Race ECMs can usually be identified by the ***printed*** RACE USE ONLY
marking on the casing. Factory race ECMs can usually be identified by the
***engraved*** RACE USE ONLY marking on the casing.

USB adapters are configured by EcmDroid automatically. See the
[user guide](docs/user-guide.md) for all connection types.

## Supported ECMs

BUEIA, BUEGC, BUEJA, BUEKA (DDFI) · BUECB, BUEGB, BUEIB, BUEIC, B2RIB (DDFI-2) ·
BUEOD, BUEWD, BUEYD, BUEZD, BUE1D, BUE2D, BUE3D, B3R1D, B3R2D, B3R3D (DDFI-3).
See [docs/supported-ecms.md](docs/supported-ecms.md) for model years and
details.

## Documentation

| For riders                                  | For developers                              |
|---------------------------------------------|---------------------------------------------|
| [User guide](docs/user-guide.md)            | [Architecture](docs/architecture.md)        |
| [Supported ECMs](docs/supported-ecms.md)    | [Serial protocol](docs/protocol.md)         |
| [Glossary & related software](docs/glossary.md) | [EEPROM layout, burning, files](docs/eeprom.md) |
|                                             | [ECM database](docs/database.md)            |
|                                             | [Live data & logging](docs/logging.md)      |
|                                             | [Development guide](docs/development.md)    |

### Calibration converter (in testing)

[`tools/calconv`](tools/calconv/README.md) is an offline PC tool that carries a
tune from one ECM firmware ID to another, e.g. a BUE2D tune onto a BUEYD ECM.
**It's in testing: don't burn its results on an ECM that runs a motorcycle
yet.** Start with the one-page [overview](docs/calibration-converter-overview.md).
Riders then read the [how-to](docs/calibration-converter-howto.md), developers the
[plan and rules](docs/calibration-converter.md).

## Building

```sh
./gradlew assembleDebug           # needs JDK 17+ and the Android SDK (platform 34)
./gradlew connectedAndroidTest    # instrumented tests on a device/emulator
```

Release builds are signed only if a `keystore.properties` file is present. See
the [development guide](docs/development.md).

Also check out [ecmsim](https://github.com/ecmdroid/ecmsim), which can be used
for testing and debugging EcmDroid without a real ECM.

## Related software

- [EcmSpy for Mono](https://ecmspy.com/downloads.shtml): the ECMSpy desktop
  application (the original Windows EcmSpy is deprecated). It uses the same
  `.xpr` EEPROM image format and can open EcmDroid's binary logs.
- [TunerPro RT](https://www.tunerpro.net): map editing with the Buell
  XDF/ADX definitions.
- [MegaLogViewer](https://www.efianalytics.com/MegaLogViewer/): for `.msl`
  logs.

## License and credits

EcmDroid is free software, licensed under the GNU General Public License
version 3 or later (see [LICENSE](LICENSE)).

- EcmDroid © 2012 Michel Marti
- Launcher icon © 2012 Lutz Gebhardt
- ECM database © 2012 the ecmspy.com project
- BLE serial implementation © 2019 Kai Morich
- usb-serial-for-android © 2013 Mike Wakerly
- USB serial implementation © 2026 Andrew Lindsay
- Bin2Msl converter code contributed by Gunter

The changelog is in [CHANGES](CHANGES).
