# EEPROM: Layout, Reading, Burning and Files

The ECM keeps its configuration and calibration in EEPROM: settings, limits,
fuel and spark maps, adaptive values, stored trouble codes and manufacturing
data. EcmDroid mirrors the whole EEPROM in one byte array (`EEPROM.data`),
which you can edit locally and write back ("burn") page by page.

## Pages

The EEPROM is addressed as numbered **pages** of up to 256 bytes (the protocol
uses one byte each for page and offset, see [protocol.md](protocol.md)). The
database defines the page list for each ECM layout (table `pages`, see
[database.md](database.md)):

- **Pages 1…n** hold the bulk of the data. Most are 256 bytes; the last page of a
  layout is usually shorter.
- **Page 0** is special. Only some layouts have it. It's small (4 bytes on
  DDFI-2 BUEGB/BUEIB, 32–40 bytes on DDFI-3), and it holds frequently updated
  or per-unit data:
  - DDFI-2: Baro Pressure Sensor value (`KBaro`) and stored error byte
    (`HDiag0`)
  - DDFI-3: stored error bytes (`HDiag0`–`HDiag6`), `KBaro`, Front AFV
    (`LFuel1`), manufacturing date/serial (`KMFG_*`), odometer (`Odo`), VIN
    (`KVIN`), security PIN data (`Sec_*`), Active Intake counter
    (`AIC_Count`), and others

DDFI-1 ECMs (BUEIA, BUEGC, BUEJA, BUEKA) and the DDFI-2 BUECB have no page 0.

The manufacturing data isn't in page 0 on every family. On DDFI and DDFI-2,
the manufacturing date and serial number (`KMFG_Year`, `KMFG_Day`,
`KMFG_Serial`) are in **page 1**, at offsets 9–13. Only on DDFI-3 are they in
page 0. So on DDFI and DDFI-2 they can be edited and burned like any other
page-1 value, and burning an image taken from another ECM also writes that
ECM's serial number and date.

## In-memory image and addressing

`EEPROM.get(id, ctx)` builds the page list from the database. Pages are laid
out **in page-number order starting with page 1**, and **page 0 is appended at
the end**:

```
buffer offset  0                                         size        xsize
               | page 1 | page 2 | ... | page n          | page 0 |
```

- `eeprom.size` is the sum of pages 1…n. `eeprom.xsize` is `size` plus page 0
  (`size == xsize` if there is no page 0).
- Every variable offset in the database (`eeoffsets.offset`) is a **buffer
  offset**, not a page/offset pair.
- **Negative offsets address page 0**, counted from the end of the buffer
  (`-1` is the last byte). `Variable.refreshValue()` and `Bit.refreshValue()`
  turn them into `buffer.length + offset`.

Example (BUEIB, verified by `TestEEPROM`): pages 1–6 start at `0x000`, `0x100`,
`0x200`, `0x29E`, `0x39E` and `0x49E`, and page 0 starts at `1206`. The
in-memory image is 1210 bytes.

`EEPROM.hasPageZero()` is true when the image length equals `xsize`. If an
image comes without page 0 (for example a file saved by a tool that leaves it
out), EcmDroid hides every page-0 variable instead of reading garbage
(`ECM.getEEPROMValue()`, `ECM.getEEPROMBit()`, `ECM.getErrors()`).

## Reading ("fetch")

`FetchTask` runs on every successful connect (`MainActivity.ConnectTask` extends
it) and from the EEPROM editor menu:

1. `ECM.setupEEPROM()` reads the version string, takes its first 5 characters as
   the ECM ID and builds an empty `EEPROM` for that layout. An unknown ID ends
   with *"Unsupported ECM Version"*.
2. One runtime data frame is read.
3. Every page is read with `ECM.readEEPromPage()`:
   - pages ≥ 1: in chunks of up to 16 bytes, page-relative offsets `0…len-1`;
   - page 0: **one byte per request**, at page offsets
     `0xFF - len + 1 … 0xFF`. Page 0's data is the *last* `len` bytes of its
     256-byte address space.

The response length is checked against the requested count, and each chunk is
copied to `page.start() + i` in the buffer.

## Editing

There are three ways to change the image. All of them mark the affected page
dirty with `EEPROM.touch(offset, length)`, which marks page 0 for negative
offsets:

- **Setup screen** (`SetupFragment`): typed values and bit flags. The values go
  through `Variable.parseValue()` + `ECM.setEEPROMValue()`, and the bit flags
  through `ECM.setEEPROMBits()`.
- **EEPROM editor** (`EEPROMFragment`): long-press a cell to edit one raw byte
  (`CellEditorDialogFragment`). Tapping a cell shows the variable that covers it
  (`VariableProvider.getNearestEEPROMVariable()`), along with the byte and 16-bit
  values in both endiannesses.
- **Loading a file** (see below). This marks every page dirty.

Values are encoded little-endian. Writing a scaled value reverses the conversion
(`(value - translate) / scale`) and truncates the result to an integer
(`Variable.updateValue()`).

## Burning (writing back)

`BurnTask` writes the image back to the ECM. Several safety rails apply:

1. **Burning is off by default.** The preference *Enable EEPROM burning*
   (`enable_burn_eeprom`) must be on, or the Burn menu entry and the Setup
   screen's *Apply Changes* button do nothing.
2. The user has to confirm a warning dialog.
3. Before writing, the task re-reads the ECM version, and the version must
   **start with the image's ECM ID**. If it doesn't, the burn is cancelled
   (*"ECM ID does not match current EEPROM ID"*).
4. Pages are written in 16-byte `W` requests. With *Optimized burning*
   (`enable_fast_burning`), only dirty pages are written. Without it, every page
   is rewritten.

**Page 0 is written selectively.** Instead of the whole page, only the
variables in `ECM.PAGE_ZERO_VARS_TO_WRITE` are sent: `LFuel1` (Front AFV) and
`KBaro` (Baro Pressure Sensor value). The page-0 write offset for a variable is
`0x100 + offset`, where `offset` is the variable's negative buffer offset. This
leaves the rest of page 0 alone: counters, VIN, odometer, security data and,
on DDFI-3, the manufacturing data. (On DDFI and DDFI-2 the manufacturing date
and serial number are in page 1, so a burn writes them.) On
BUEOD the Front AFV variable is named `LFuel1_LD`, so the page-0 burn only
writes `KBaro` there.

After a successful burn, every page is marked clean (`EEPROM.saved()`).

Known open issues in this area:
values are truncated instead of rounded when written, entered values aren't
range-checked, page-0 hex edits other than `LFuel1`/`KBaro` are silently not
burned, and burning an `.epr` image fails on layouts with page 0.

## EEPROM files (`.xpr`)

EcmDroid uses the same two EEPROM file flavours as ECMSpy. ecmspy.com's
[supported ECM list](https://ecmspy.com/supported.shtml) gives both sizes for
each ECM type (e.g. BUEIB: `.xpr` 1210 bytes, `.epr` 1206 bytes):

| Extension | Content                                           | Size            |
|-----------|---------------------------------------------------|-----------------|
| `.xpr`    | pages 1…n followed by page 0                      | `eeprom.xsize`  |
| `.epr`    | pages 1…n only (legacy, no page 0)                | `eeprom.size`   |

Both are raw byte images with no header. For layouts without page 0, the two
sizes are equal.

**Save** (`EEPROMFragment` → *Save*) writes the in-memory image unchanged. That
is an `.xpr` image when page 0 exists or the file was loaded as `.xpr`. The file
name is `<ECM-ID>_<yyyyMMdd-HHmmss>.xpr` (`HH` is written as `kk`, 1–24), and
the file is stored through the Storage Access Framework. The changelog (v0.5)
records this as the switch to ECMSpy's `.xpr` format. If the image came from an
`.epr` file, the saved file has no page 0 either, even though it gets the `.xpr`
extension.

**Load** (*Load* menu) works for any file name and extension:

1. The ECM type is derived **from the file size**: `EEPROM.size2id()` finds every
   ECM ID whose `size` or `xsize` matches.
2. If more than one ID matches, the user picks one. For example, BUEIB, BUEIC and
   B2RIB share 1206/1210 bytes, and every B3Rx/BUExD pair shares its layout.
3. The image is loaded and every page is marked dirty, so a later burn writes
   all of it.
4. If an ECM is connected, the loaded ID must match the connected ECM's ID.
   Otherwise you get *"Incompatible ECM version. Please disconnect first."*

`.epr` files load the same way. Only the size matters. An `.epr` image has no
page 0, so page-0 values (stored errors on DDFI-3, Front AFV, Baro, …) aren't
available for it.

## Values shown on the ECM Information screen

After a fetch, `MainFragment` shows:

| Field             | Source                                                                   |
|-------------------|--------------------------------------------------------------------------|
| ECM ID / version  | version string (first 5 chars / full string)                             |
| EEPROM size/pages | image length, page count (including page 0)                              |
| ECM type          | `eeprom.type` (`DDFI`, `DDFI-2`, `DDFI-3`)                               |
| Serial number     | `KMFG_Serial`                                                            |
| Mfg. date         | `KMFG_Year` (+2000; ≥ 2090 is read as 199x) and `KMFG_Day` (0-based day of year) |
| Layout revision   | `CSR`                                                                    |
| Country ID        | `Country_ID`; if it's 255, then `S<KID_Series>-M<KID_Market>-V<KID_Version>` |
| Calibration ID    | `Cal_ID`                                                                 |
