# Live Data, Log Recording and MSL Conversion

## Runtime data polling

`EcmDroidService` is a bound, non-exported service. Its background
`ReaderThread` (`"ECM-Reader-Thread"`) polls the ECM for runtime data whenever
the link is connected **and** either live reading (Data Channels screen) or
recording (Log Recorder) is on. Otherwise the thread blocks on `wait()` until
`startReading()` or `startRecording()` notifies it.

Each cycle:

1. `ECM.readRTData()` sends `'C'` and stores the full response frame (see
   [protocol.md](protocol.md#runtime-data-block)). `ECM.getRuntimeData()`
   returns it.
2. The service broadcasts `org.ecmdroid.Service.realtimedataevent`
   (`EcmDroidService.REALTIME_DATA`).
3. If it's recording, it appends a record to the log (see below).
4. It sleeps until the interval has passed. The interval is the recording
   interval, at least **50 ms**. After a failed read, the interval is at least
   **250 ms** and the service's read-failure counter goes up.

Screens subscribe to `REALTIME_DATA` with `registerReceiver(...,
RECEIVER_NOT_EXPORTED)` and re-render from `ECM.getRuntimeData()`:

- **Data Channels** (`DataChannelFragment` + `DataChannelAdapter`): five
  user-selectable channels. Defaults are `Batt. Voltg.`, `RPM`, `TPD`, `AFV`,
  `CLT`. Selections are saved in the activity's private preferences as
  `channel1`…`channel5`. Scalar channels show a value and a progress bar scaled
  to the variable's `high`. Bitfield channels show eight checkboxes.
- **Log Recorder** (`LogFragment`): record and byte counters, plus live `TPD`,
  `RPM` and `CLT`.

`EcmDroidService` also broadcasts `RECORDING_STARTED` and `RECORDING_STOPPED`.

## Recording

From the Log Recorder screen:

- The **storage location** is a Storage Access Framework tree URI picked in
  Preferences (*Log Storage Location*, saved as `storage.location`). Recording
  won't start until one is set.
- **Interval** choices: *No Delay* (0 → effectively 50 ms), 250 ms, 500 ms,
  1 s, 2 s, 5 s.
- On Android 13+ the app asks for the notification permission first. A
  persistent notification ("Recording started") stays up while recording.
- The optional *Keep Screen On* preference keeps the screen on during
  recording.
- File name: `yyyyMMdd_HHmmss.bin` (written with `kk`, so hours run 1–24),
  MIME type `application/x-ecmdroid-binlog`.

### Binary log format (`.bin`)

```
+-----------------+-----------------------------------------------------------+
| 5 bytes         | ECM ID, ASCII (e.g. "BUEIB"), or "UNKWN" if unknown       |
+-----------------+-----------------------------------------------------------+
| repeated until EOF:                                                         |
|   4 bytes       | timestamp, big-endian int, 1/100 s since recording start  |
|   poll_len B    | complete runtime data response frame (99/103/107/135 B)   |
+-----------------------------------------------------------------------------+
```

Records aren't delimited. The reader has to know the frame length for the ECM
ID. EcmSpy for Mono can open these files directly: its user guide lists
"Binary log files from EcmSpy for Palm PDA or EcmDroid" as supported.
[ecmsim](https://github.com/ecmdroid/ecmsim) can replay them. You can check each record by its XOR checksum (last byte = XOR of bytes
1 … n-2).

Example (`app/src/androidTest/resources/BUEIB_log.bin`):

```
42 55 45 49 42                  "BUEIB"
00 00 00 11                     t = 0.17 s
01 42 00 64 FF 02 06 7B 58 ...  107-byte runtime frame
```

## MSL (MegaLogViewer) conversion

If *Convert to MSL* is on when recording stops, `LogFragment.StopTask` runs
`util.Bin2MslConverter` on the finished `.bin` file and writes
`yyyyMMdd_HHmmss.msl` (MIME type `application/x-ecmdroid-msl-log`) next to it.
The converter code was contributed by Gunter (changelog v0.9). The output is a
tab-separated text file for [MegaLogViewer](https://www.efianalytics.com/MegaLogViewer/):

```
"EcmDroid/Bin2Msl BUE2D"
Number<TAB>Time<TAB>Gego<TAB>Gego1<TAB>Engine<TAB>Load<TAB>Load1<TAB>RPM<TAB>...
1<TAB>0.17000<TAB>100<TAB>...
```

### How the converter works

1. It reads the 5-byte ID and maps it to a **category** and frame length:

   | ID prefix / ID                                   | Category | Frame | Column definition file |
   |--------------------------------------------------|---------:|------:|------------------------|
   | `KA`, `JA` (BUEKA, BUEJA)                        | 1        | 99    | `runtime1.tab`         |
   | `CB` (BUECB)                                     | 2        | 103   | `runtime2.tab`         |
   | `GB`, `IB`, `IC` (BUEGB, BUEIB, BUEIC, B2RIB)    | 2        | 107   | `runtime2.tab`         |
   | `OD`, `WD`, `YD`, `ZD`, `1D`, `2D`, `3D`, B3R1D, B3R3D | 3  | 135   | `runtime3.tab`         |

2. It loads the column definitions from `app/src/main/resources/runtime{1,2,3}.tab`.
   These are tab-separated, 19 columns per line. The converter uses column 6
   (size), 7 (frame offset), 9 (scale), 10 (translate), 12 (format; `0` =
   integer) and 17 (MSL column header). Lines whose offset doesn't fit the
   frame are skipped.
3. For each record it checks the XOR checksum. **Records with a bad checksum are
   dropped** and counted. It then writes:
   - `Number`: 1-based record counter
   - `Time`: timestamp / 100, in seconds
   - `Gego` (and `Gego1` on DDFI-3): `EGO Corr.` / `EGO1 Corr.` in closed loop
     (Flags2 bit 7 set), otherwise `AFV` / `AFV1`, divided by 10
   - `Engine`: a MegaSquirt-style engine status byte built from Flags1, warm-up
     enrichment (`WUE` ≥ 1020 → bit 3) and acceleration correction
     (`Accel Corr.` ≥ 10 → bit 4):

     | Bit | Meaning     | Source                                  |
     |-----|-------------|-----------------------------------------|
     | 0   | running     | Flags1 bit 0                            |
     | 3   | warm-up     | `WUE` ≥ 1020                            |
     | 4   | TPS accel   | Flags1 bit 2, or `Accel Corr.` ≥ 10     |
     | 5   | decel       | Flags1 bit 3                            |
     | 7   | idle        | Flags1 bit 6                            |

   - one column per `.tab` line: `raw × scale + translate`. Values are
     little-endian, 1 or 2 bytes.
4. The progress is reported to the UI through `java.util.Observable`. You can
   cancel the conversion.

### Known limitations

- The converter doesn't recognise the IDs **BUEIA**, **BUEGC** and **B3R2D**
  (DDFI-1 categories 3/4 and the DDFI-3 race ECM with the 2D layout). Logs from
  those ECMs fail with *"Unsupported ECM Type"*. A log recorded while no ECM ID
  was known (`UNKWN`) can't be converted either.
- The `.tab` files are a separate copy of the runtime layouts, not generated
  from the database. Keep them consistent by hand when the database changes.

## Trouble codes

`ECM.getErrors(ErrorType)` uses the bit sets from the database:

| Type      | Variables                                  | Data source                                                   |
|-----------|--------------------------------------------|---------------------------------------------------------------|
| `CURRENT` | `CDiag0`, `CDiag1`, … (runtime)            | last runtime frame                                            |
| `STORED`  | `HDiag0_LD`, `HDiag1_LD`, … (runtime)      | last runtime frame                                            |
| `STORED`  | `HDiag0`, `HDiag1`, … (EEPROM)             | EEPROM image. Fallback when not connected but an image is loaded |

It reads `…Diag0`, `…Diag1`, … until a name isn't defined. Each set bit becomes
an `Error`, with the code from `bits.dtcN` and the text from `bits.bitN`. Page-0
error bytes are skipped if the image has no page 0. *Clear* on the Trouble Codes
screen sends function `0x01` (Clear codes) and then re-reads the runtime data.
