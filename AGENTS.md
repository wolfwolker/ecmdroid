# AGENTS.md

Guidance for AI coding agents and assistants working in this repository. Human
contributors should start with [README.md](README.md) and [docs/](docs/README.md).

## Project

EcmDroid is an Android app (Java, package `org.ecmdroid`) to diagnose and tune Buell motorcycles with DDFI (tube-frame 1999–2002), DDFI-2 (XB 2003–2007) and DDFI-3 (XB 2008+, 1125R/CR) ECMs. It's heavily based on the ecmspy.com project: the protocol, the ECM definition database and the `.xpr`/`.epr` EEPROM formats come from there. Reference tools for the same job are ECMSpy **Mono** edition (the original ECMSpy is deprecated, so don't use it as a reference) and TunerPro. It connects to the diagnostic plug through Bluetooth SPP, BLE, USB-to-serial or TCP ([ecmsim](https://github.com/ecmdroid/ecmsim) simulator).

Full documentation is in `docs/` (start at `docs/README.md`). The protocol, EEPROM, database and logging docs there are the reference for byte-level details.

## Build & test

Single-module Gradle project (`:app`), Kotlin DSL, version catalog in `gradle/libs.versions.toml`. Needs JDK 17+ and the Android SDK (platform 34).

```sh
./gradlew assembleDebug            # debug APK
./gradlew assembleRelease          # signed only if keystore.properties exists at repo root
./gradlew connectedAndroidTest     # instrumented tests (needs a device/emulator)
./gradlew connectedAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=org.ecmdroid.TestPDU
```

All tests live in `app/src/androidTest` (no JVM unit tests). They load fixture ECM dumps (`.eeprom`, `.bin` runtime/log captures, `.msl`) from `app/src/androidTest/resources` via `TestUtils`, and several assert exact DB-derived counts and offsets.

Java source/target is 1.8; indent with tabs; GPL v3 header on every source file. Releases: bump `versionCode`/`versionName` in `app/build.gradle.kts`, add a `CHANGES` entry, commit "Prepare vX.Y.Z", tag `ecmdroid-vX.Y.Z`.

### Offline tools

`tools/calconv/` is the calibration converter: an offline Python (3.11+, standard library only) helper that compares and, later, converts `.xpr` images between firmware layouts. It reads the app's bundled DB directly. Python code uses 4-space indents and the same GPL header as a comment. The plan and its rules are in `docs/calibration-converter.md`, and usage in `tools/calconv/README.md`.

```sh
tools/calconv/test.py                              # tests (pkgx shebang; or: python3 tools/calconv/test.py)
tools/calconv/calconv.py plan --from BUE2D --to BUEYD
tools/calconv/calconv.py diff a.xpr b.xpr          # exit code 1 if they differ
```

When you change the DB or the definition logic, expect `tools/calconv/tests/test_plan.py` counts to change. Update `docs/calibration-converter.md` with them. Never commit real ECM images without scrubbing page 0 (VIN, serial number, odometer, security PIN).

## Architecture

- **`ECM`** (singleton) owns the link (one `connect(...)` overload per transport, all adapted to an `InputStream`/`OutputStream`), the current `EEPROM` image and the last runtime frame. `sendPDU()` is `synchronized` because UI tasks and the service's reader thread share the link. `MainActivity.ConnectTask` extends `FetchTask`, so every connect also identifies the ECM and reads the whole EEPROM.
- **`PDU`**: frame = `01 src dst len FF 02 body… 03 xor`, checksum = XOR of bytes 1..EOT. ECM address is a static global set by `PDU.setProtocol()`: `STOCK` 0x42 / 9600 baud, `FACTORY_RACE` 0x55 / 19200 baud.
- **ECM ID** = first 5 chars of the version string (e.g. `BUEIB`). It keys every DB lookup.
- **Variable metadata comes from the bundled SQLite DB** (`assets/ecmdroid.db.gz`, from ecmspy.com), not code. EEPROM variables are looked up by `names.varname`, runtime variables by `names.origname`.
- **Offsets that trip people up:**
  - Runtime variable offsets are relative to the **full response frame** (first data byte = offset 7). `readRTData()` returns the whole frame.
  - EEPROM offsets are offsets into the in-memory image: pages 1..n in order, then page 0 appended at the end. **Negative offsets = page 0**, counted from the end of the image.
  - Values are little-endian; physical = raw × scale + translate.
- **Page 0**: read byte-by-byte at page offsets `0xFF-len+1..0xFF`. Burns only write `ECM.PAGE_ZERO_VARS_TO_WRITE` (`LFuel1`, `KBaro`), not the whole page.
- **`DBHelper.setupDB()`** reinstalls the DB when the device's `user_version` differs from `DBHelper.DB_VERSION`. **Any change to the DB asset requires bumping `DB_VERSION`**. To regenerate the DB, see `README.db` / `docs/database.md`.
- **`EcmDroidService`** (bound service, not foreground) polls runtime data on a reader thread, broadcasts `REALTIME_DATA`, and records binary logs (`5-byte ID` + repeated `[int32 BE centiseconds][frame]`). `util/Bin2MslConverter` converts them to MegaLogViewer `.msl` using the hand-maintained `app/src/main/resources/runtime{1,2,3}.tab`. These aren't generated from the DB.
- **UI**: `MainActivity` hosts **framework** (`android.app`) fragments; blocking I/O runs in `ProgressDialogTask` (AsyncTask) subclasses. The Setup screen is driven by `res/xml/ecm_setup.xml`, where preference keys are DB variable names (`Var`, `Var[bit,…]`, alternatives `A:B`). Adding a setting usually needs no Java.
- EEPROM writes are gated by the `enable_burn_eeprom` preference, and `BurnTask` checks that the connected ECM's version starts with the image's ECM ID.
- `de.kai_morich.simple_bluetooth_le_terminal` is vendored third-party BLE serial code.
