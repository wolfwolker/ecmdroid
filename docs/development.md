# Development Guide

## Prerequisites

- **JDK 17 or newer.** Gradle 9.4.1 and Android Gradle Plugin 9.2.1 need it.
  The Gradle wrapper downloads Gradle itself.
- **Android SDK** with platform 34 (`compileSdk 34`). Point to it with
  `ANDROID_HOME` or a `local.properties` file (`sdk.dir=/path/to/sdk`). Android
  Studio creates this file for you. It's git-ignored.
- Network access to Google Maven, Maven Central and **JitPack**
  (`usb-serial-for-android` comes from JitPack, see `settings.gradle.kts`).

## Building

```sh
./gradlew assembleDebug        # app/build/outputs/apk/debug/app-debug.apk
./gradlew installDebug         # build and install on a connected device
./gradlew assembleRelease      # release APK (minification is off)
./gradlew lint                 # Android lint
```

### Release signing

Signing is optional. `app/build.gradle.kts` only configures a release signing
config if a `keystore.properties` file exists at the repository root
(git-ignored):

```properties
storeFile=/absolute/or/relative/path/to/release.keystore
storePassword=…
keyAlias=…
keyPassword=…
```

`storeFile` is resolved relative to `app/`. Without this file,
`assembleRelease` produces an unsigned APK.

## Tests

All tests are **instrumented tests** in `app/src/androidTest`. They need a
device or emulator, because most of them use the real SQLite database through
an Android `Context`.

```sh
./gradlew connectedAndroidTest
# one class
./gradlew connectedAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=org.ecmdroid.TestPDU
# one method
./gradlew connectedAndroidTest -Pandroid.testInstrumentationRunnerArguments.class=org.ecmdroid.TestECM#testErrorParsing
```

| Test class             | Covers                                                                                    |
|------------------------|-------------------------------------------------------------------------------------------|
| `TestPDU`              | frame building and parsing, checksums, request encoding (exact hex)                       |
| `TestEEPROM`           | BUEIB page layout and page start offsets                                                  |
| `TestVariableProvider` | DB lookups, variable counts for BUE2D, scaling, axis and table decoding, value write-back |
| `TestBitSetProvider`   | bitset definitions and active-bit detection on a real runtime frame                       |
| `TestECM`              | trouble-code decoding, serial number and manufacturing date from fixture data             |
| `TestBin2Msl`          | converting a recorded BUEIB binary log                                                    |

Fixtures live in `app/src/androidTest/resources` and are loaded as classpath
resources (`TestUtils`):

| File                                       | Content                                                    |
|--------------------------------------------|------------------------------------------------------------|
| `BUEIB.eeprom`                             | BUEIB EEPROM image without page 0 (1206 bytes)             |
| `BUE2D.eeprom`                             | BUE2D EEPROM image with page 0 (3796 bytes)                |
| `RT_BUEIB.bin`, `RT_BUEIB242.bin`, `BUEIB.bin` | single 107-byte BUEIB runtime frames                   |
| `BUEIB_log.bin`, `BUE2D_log.bin`           | binary logs in the format described in [logging.md](logging.md) |
| `BUE2D_log.msl`                            | MSL conversion of the BUE2D log                            |

Several assertions depend on the bundled database (variable counts, offsets).
If you update the database, expect to update these tests.

## Testing without a motorcycle

[ecmsim](https://github.com/ecmdroid/ecmsim) is a small Java (Maven) program
that simulates an ECM over TCP for testing and debugging EcmDroid:

```sh
./ecmsim.sh BUEIB            # simulate a BUEIB on the default port 6275
./ecmsim.sh --list           # list the ECM types it knows
# options: --port <n>, --xpr <file> (EEPROM image), --log <file> (.bin log to replay), --debug
```

It answers `V`, `R`, `W` and `C` requests, replies NAK to frames with a bad
checksum, and reports "busy" for a few seconds after a function write to page
`0x20`. It serves the EEPROM from an `.xpr` file (or an empty image), and
replays runtime data from a `.bin` log (BUEIB and BUE2D logs are bundled) or
returns random data. It always answers as the stock ECM address `0x42`, so use
the *Stock / P&A* protocol in EcmDroid. See the ecmsim README for details.

In EcmDroid, set **Settings → ECM Connection → TCP/IP**, enter the simulator's
host and port `6275`, and connect. On the Android emulator, the host machine is
`10.0.2.2`.

The same TCP transport works with WiFi-to-serial bridges.

## Project layout

```
app/src/main/java/org/ecmdroid/          core model, service, providers, adapters
app/src/main/java/org/ecmdroid/activities MainActivity, PrefsActivity, AboutActivity
app/src/main/java/org/ecmdroid/fragments  one fragment per screen (+ TorqueValuesFragment activity)
app/src/main/java/org/ecmdroid/task       AsyncTask-based fetch / burn / progress dialogs
app/src/main/java/org/ecmdroid/util       Bin2MslConverter
app/src/main/java/de/kai_morich/…         vendored BLE serial code
app/src/main/assets/                      ecmdroid.db.gz (ECM definitions), about.html
app/src/main/resources/                   runtime{1,2,3}.tab (MSL converter column definitions)
app/src/main/res/xml/                     ecm_setup.xml (Setup screen), app_prefs.xml,
                                          torque_values.xml, device_filter.xml (USB)
scripts/                                  mysql2sqlite.sh (DB import), mklocalversion
docs/                                     this documentation
```

`scripts/mklocalversion` prints a `VCS` Java interface with a git-describe
style suffix (`-g<sha>`, `-dirty`). It's left over from the pre-Gradle build
and isn't wired into the current build.

## Conventions

- Java 8 language level. Lambdas are fine, but avoid newer APIs that would
  break `minSdk 26`.
- Indent with **tabs**, matching the existing sources.
- Each source file starts with the GPL v3 license header.
- The UI uses framework (`android.app`) fragments and preference screens, plus
  `AsyncTask` via `ProgressDialogTask`. New screens should follow the same
  pattern unless the whole UI is migrated.
- Never block the UI thread with ECM I/O. Use a `ProgressDialogTask` or the
  service.
- ECM knowledge belongs in the database or `ecm_setup.xml`, not in Java code.
- User-visible strings go in `res/values/strings.xml` (English only for now).

## Common tasks

### Adding a Setup screen parameter

Add a preference to `res/xml/ecm_setup.xml` with the variable name as key. Use
`Name[bit,…]` for flags and `A:B` for per-layout alternatives. See
[architecture.md](architecture.md#the-setup-screen-dsl-resxmlecm_setupxml).

### Supporting a new ECM version

1. Make sure the database has an `eeprom` row for the 5-character ID, with a
   category that has `pages`, `eeoffsets` and `rtoffsets` rows. Usually this
   means importing a newer ecmspy.com database ([database.md](database.md#updating-the-database)).
2. Bump `DBHelper.DB_VERSION`.
3. If logs from this ECM should convert to MSL, add its ID to the ID switch in
   `Bin2MslConverter.convert()` and make sure a matching `runtime*.tab`
   exists.
4. If the Front AFV or another page-0 value must be burnable, check
   `ECM.PAGE_ZERO_VARS_TO_WRITE`.

### Releasing

The existing *"Prepare vX.Y.Z"* commits follow this pattern:

1. Bump `versionCode` and `versionName` in `app/build.gradle.kts`.
2. Add an entry at the top of `CHANGES`.
3. Update the copyright line in `app/src/main/assets/about.html` if needed.
4. Commit as *"Prepare vX.Y.Z"* and tag `ecmdroid-vX.Y.Z`.
