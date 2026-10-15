# The ECM Definition Database

EcmDroid has almost no ECM knowledge hard-coded. Page layouts, variable
offsets, sizes, scaling, units, labels, bit meanings and trouble codes all come
from a bundled SQLite database derived from the **ecmspy.com** project's
database. The About screen credits it as *"ECM Database (c) 2012 by the
ecmspy.com project"*.

- Source file: `app/src/main/assets/ecmdroid.db.gz` (gzip-compressed SQLite 3)
- Current content: ecmspy.com DB snapshot `d00bc92f-20150424` (commit
  *"Update ecmspy database to d00bc92f-20150424"*, August 2019, released in
  v0.99)
- Schema version constant: `DBHelper.DB_VERSION = 201504242`
- Origin and licence: according to the EcmDroid maintainer
  ([#24](https://github.com/ecmdroid/ecmdroid/issues/24)), the maintainer of
  ecmspy.com and the EcmSpy desktop app supplied the dumps (2012, and an update
  in 2019) and gave permission to use them in EcmDroid under the GPLv3. Newer
  versions have to come through the same channel. ecmspy.com has no public
  download of the database.

## Installation on the device

`EcmDroidApp.onCreate()` calls `DBHelper.setupDB()` before any UI starts:

1. It opens `ecmdroid` in the app's database directory and reads the SQLite
   `user_version` pragma.
2. If that differs from `DBHelper.DB_VERSION`, it deletes the database and
   copies the `ecmdroid.db` asset over it.
3. It opens the database once through `SQLiteOpenHelper` so that
   `user_version` gets set to `DB_VERSION`.

The code opens the asset as `ecmdroid.db`, but the repository stores it as
`ecmdroid.db.gz`. The Android build un-gzips `.gz` assets when it packages the
APK, and it has worked this way since the first commit. Keep the file gzipped.

The bundled file itself has `user_version = 0`. The version check relies only
on `DB_VERSION` in the code, so **every database change must bump
`DBHelper.DB_VERSION`**. If it isn't bumped, existing installs keep their old
copy. The version follows the pattern `yyyymmdd` plus a single revision digit
(`20150424` + `2`).

## Tables

The schema comes from the ecmspy.com MySQL dump. EcmDroid reads the columns
listed in **bold**. The other columns are kept because they're part of the
upstream dump.

### `eeprom`: one row per ECM ID

| Column                                     | Meaning                                                                              |
|--------------------------------------------|--------------------------------------------------------------------------------------|
| **`name`**                                 | 5-character ECM ID, matched against the first 5 chars of the version string         |
| **`category`**                             | layout key. Joins to `pages`, `eeoffsets`, `rtoffsets`. IDs with the same layout share one |
| **`type`**                                 | `DDFI`, `DDFI-2` or `DDFI-3` (→ `ECM.Type`)                                          |
| **`size`**, **`xsize`**                    | image size without / with page 0. Used for file-size → ID detection                  |
| `pages`                                    | number of pages excluding page 0                                                     |
| `poll_len`                                 | runtime data frame length (99/100/103/107/135)                                       |
| `file`, `remark`, `Secret`, `uniqueid`     | upstream metadata (`remark` e.g. "Buell Street ECM, OEM", "EBR Race ECM")           |

### `pages`: page list per layout

`category`, `page`, `size`. Page 0 is the special page described in
[eeprom.md](eeprom.md#pages).

### `eeoffsets`: EEPROM variables per layout

| Column                         | Meaning                                                                                       |
|--------------------------------|-----------------------------------------------------------------------------------------------|
| **`category`**, **`varname`**  | layout and internal variable name (e.g. `KTemp_Fan_On`, `Tab_Fuel_Front`)                     |
| **`type`**                     | `Value`, `Bits`, `Array`, `Axis`, `Table`, `Map`, `String` (→ `Variable.DataType`)            |
| **`size`**                     | total size in bytes                                                                           |
| **`offset`**                   | buffer offset in the EEPROM image. **Negative = page 0**, counted from the end               |
| **`scale`**, **`translate`**   | conversion to physical units                                                                  |
| **`elemsize`**                 | bytes per element (1 or 2) for arrays/axes/tables/maps                                        |
| **`cols`**, **`rows`**         | table/map dimensions                                                                          |
| `xaxis`, `yaxis`               | names of the axis variables of a map (e.g. `Tab_Fuel_RPM_Ax`, `Tab_Fuel_Load_Ax`)             |
| `elements`, `skip`, `axisscale`, `axistranslate` | not used by EcmDroid                                                        |

### `rtoffsets`: runtime (live data) variables per layout

| Column                                         | Meaning                                                                        |
|------------------------------------------------|--------------------------------------------------------------------------------|
| **`category`**, **`varname`**                  | layout and internal name                                                       |
| **`type`**                                     | `Scalar` or `Bitfield`                                                         |
| **`size`**, **`offset`**                       | position inside the **complete response frame** (offset 7 = first data byte)   |
| **`scale`**, **`translate`**                   | conversion to physical units                                                   |
| **`low`**, **`high`**, **`ulow`**, **`uhigh`** | display range (used to scale the Data Channels progress bar)                   |
| **`secret`**                                   | `1` = hidden (frame header bytes and undocumented values)                      |

### `names`: labels, units and formats

| Column            | Meaning                                                                                             |
|-------------------|-----------------------------------------------------------------------------------------------------|
| **`varname`**     | joins to `eeoffsets.varname` / `rtoffsets.varname`                                                 |
| **`origname`**    | short display name (e.g. `TPD`, `Batt. Voltg.`, `EGO Corr.`). **Runtime variables are looked up by this name** |
| **`name`**        | long label, e.g. "Fan Key-On On Temperature"                                                        |
| **`remark`**, **`description`** | free text                                                                             |
| **`units`**       | unit name. `Units.getSymbol()` maps a few to symbols (`°`, `%`, `V`)                                |
| **`format`**      | `java.text.DecimalFormat` pattern. `"0"` means "integer"                                            |
| **`secret`**      | hide the variable                                                                                   |
| `axisunits`, `axisformat`, `monospy`, `palmspy`, `livedata`, `priority`, `idhash` | upstream metadata, not used     |

### `bits`: bitfield definitions and trouble codes

One row per bitfield variable (`varname`, e.g. `KConfig`, `CDiag0`, `HDiag3_LD`):

- `bit1`…`bit8`: description of bits 0…7 (shown as error text or as the setup
  label)
- `bitname1`…`bitname8`: short bit names
- `dtc1`…`dtc8`: diagnostic trouble code reported when that bit is set
- `byte`, `name`: byte index and title

### `adxbits`

Per-bit titles with true/false texts for the live-data bitfields (upstream
data). EcmDroid doesn't use this table.

## How lookups work

Everything is keyed by the **ECM ID** (`EEPROM.getId()`, e.g. `BUEIB`):

```sql
-- EEPROM layout (EEPROM.get)
SELECT xsize, type, page, pages.size FROM eeprom, pages
 WHERE pages.category = eeprom.category AND name = :id ORDER BY page;

-- EEPROM variable (DatabaseVariableProvider.getEEPROMVariable)
SELECT eeoffsets.*, names.*, eeprom.type FROM eeoffsets, eeprom, names
 WHERE eeprom.name = :id AND names.varname = :varname
   AND eeoffsets.category = eeprom.category AND eeoffsets.varname = names.varname;

-- Runtime variable (getRtVariable): looked up by names.origname, secret rows excluded
SELECT rtoffsets.*, names.*, eeprom.type FROM rtoffsets, eeprom, names
 WHERE eeprom.name = :id AND names.origname = :displayName
   AND rtoffsets.category = eeprom.category AND names.varname = rtoffsets.varname
   AND names.secret = 0 AND rtoffsets.secret = 0;

-- Bit set (DatabaseBitSetProvider.getBitSet), offsets from eeoffsets or rtoffsets
SELECT * FROM <eeoffsets|rtoffsets> AS offsets, bits, eeprom
 WHERE offsets.varname = :name AND bits.varname = offsets.varname
   AND eeprom.name = :id AND offsets.category = eeprom.category;
```

Two naming conventions follow from this:

- **EEPROM variables use `varname`** (`KTemp_Fan_On`, `LFuel`, `Tab_Fuel_Front`).
- **Runtime variables use `origname`** (`RPM`, `TPD`, `AFV`, `Batt. Voltg.`).
  `Constants.Variables` contains both kinds of names.

`DatabaseVariableProvider` and `DatabaseBitSetProvider` are process-wide
singletons with a cache. The cache is **cleared whenever the ECM ID changes**,
so definitions from one layout never leak into another (see changelog v0.96).

## Value conversion

`Variable.refreshValue(byte[])` reads `size / width` elements. Each element is
`width` bytes, **little-endian**. For numeric types:

```
physical = raw × scale + translate     (scale 0 and translate 0 are skipped)
```

If `format` is `"0"`, the result is truncated to an integer. `BITS` and
`BITFIELD` values are kept as raw bit patterns, and `STRING` values as
NUL-terminated ASCII. Writing (`updateValue`) applies the inverse and truncates.

171 EEPROM variable definitions combine format `"0"` with a fractional scale.
The app shows those values truncated, e.g. an idle spark advance of 13.25°
(scale 0.25) as 13.

`Variable.getHigh()` scales `high` only when `uhigh` is the full range of the
size (`0xFF` / `0xFFFF`). This matches how the upstream DB stores display
ranges.

## Database coverage

| ECM IDs                   | Category | Type   | Pages (excl. 0) | size / xsize | Runtime vars* | EEPROM vars |
|---------------------------|---------:|--------|----------------:|-------------:|--------------:|------------:|
| BUEIA                     | 3        | DDFI   | 5               | 1056 / 1056  | 62            | 146         |
| BUEGC                     | 4        | DDFI   | 5               | 1100 / 1100  | 62            | 112         |
| BUEJA, BUEKA              | 5        | DDFI   | 5               | 1072 / 1072  | 62            | 149         |
| BUECB                     | 6        | DDFI-2 | 6               | 1138 / 1138  | 67            | 214         |
| BUEGB                     | 7        | DDFI-2 | 6               | 1198 / 1202  | 70            | 233         |
| BUEIB, BUEIC              | 8        | DDFI-2 | 6               | 1206 / 1210  | 70            | 241         |
| B2RIB                     | 9        | DDFI-2 | 6               | 1206 / 1210  | 70            | 246         |
| BUE1D, B3R1D              | 49       | DDFI-3 | 14              | 3404 / 3444  | 111           | 538         |
| BUE2D, B3R2D              | 50       | DDFI-3 | 15              | 3756 / 3796  | 111           | 544         |
| BUE3D, B3R3D              | 51       | DDFI-3 | 16              | 3884 / 3924  | 111           | 666         |
| BUEOD                     | 79       | DDFI-3 | 11              | 2788 / 2820  | 115           | 413         |
| BUEWD                     | 88       | DDFI-3 | 13              | 3116 / 3156  | 115           | 519         |
| BUEYD                     | 89       | DDFI-3 | 13              | 3232 / 3272  | 115           | 533         |
| BUEZD                     | 90       | DDFI-3 | 14              | 3372 / 3412  | 112           | 539         |

\* non-secret runtime variables visible in the Data Channels list. EEPROM vars
are rows. A few names are listed twice: `KBaro_Read` on BUE1D, four on BUE3D,
and `KVS_RPM_Revs` on BUEOD, which has two different definitions. `calconv
plan` reports these as database warnings.

The offset tables also contain categories with no `eeprom` row (0, 11, 22, 33,
1051). No ECM ID can reach them.

To explore the database:

```sh
gunzip -c app/src/main/assets/ecmdroid.db.gz > /tmp/ecmdroid.db
sqlite3 /tmp/ecmdroid.db "SELECT name, category, type, size, xsize, remark FROM eeprom ORDER BY category;"
```

## Is there a newer database?

**No newer one was found (checked October 2026).**

- **The live site matches the bundled data.** ecmspy.com generates its
  per-ECM pages (`cgi-bin/ecm.cgi`, `detail.cgi`) from its live database. The
  public (non-secret) variables of all 14 layouts match the bundled database
  exactly in ID, name, offset, type and size. So do the size, elements, cols,
  scale and axis scaling of every BUEYD, BUEZD, BUE2D and BUE3D table, map,
  axis and array. Secret variables can't be checked on the site.
- **No later data versions are listed.** The site's version list
  (`cgi-bin/versions.cgi`) ends with EcmSpy for Mono 2.0.31.2 (2014-09-11) and
  "Data 3.0" (2013-05-19). No later update announcements were found.
- **The EcmSpy for Mono installer has older data.** The public installer
  (`EcmSpy_Mono_2.0-Setup.exe`) contains the definitions as .NET DataSet XML,
  dated January 2014. They're older than the bundled data: 66 variables are
  missing, e.g. `KPIF1`, `KVIN`, `Sec_PIN`, `Tab_Idle_Spark_Front` and the BUE3D
  EPS tables. The installer mentions a separate database installer for
  registered users, which wasn't checked.
- **Terms.** The ecmspy.com EULA (`cgi-bin/eula.cgi`, also in the installer)
  covers "executable or data files". It allows personal, non-commercial use and
  forbids copying the data into other products. **Don't import data from the
  installer or the site's exports into EcmDroid.** The bundled database is used
  with the maintainer's permission (see the top of this page). Updates have to
  come through the same channel.

The comparison also settled some open data questions:

- the BUEYD `.xpr` size of 3250 bytes on the supported list is most likely a
  typo, because everything else says 3272;
- the BUE2D size/element mismatches and the BUEYD `Tab_Idle_Spark` 4×4 shape
  are the same upstream.

## Updating the database

The procedure is in `README.db`. In short:

1. Import an ecmspy.com database backup (MySQL dump) into a MySQL database.
2. Convert it with `scripts/mysql2sqlite.sh -u<user> -p<password> <db> > ecmdroid.sq3`
   (a mysqldump → SQLite awk converter).
3. Remove all column `COMMENT`s (SQLite doesn't support them).
4. `sqlite3 app/src/main/assets/ecmdroid.db < ecmdroid.sq3`
   (`README.db` still shows the old, pre-Gradle path `assets/`.)
5. `gzip -f app/src/main/assets/ecmdroid.db`
6. Bump `DBHelper.DB_VERSION`.

Then check the result:

- Run the instrumented tests (`TestVariableProvider`, `TestBitSetProvider`,
  `TestEEPROM`, `TestECM`). They assert concrete offsets and counts.
- Check that every variable named in `res/xml/ecm_setup.xml` and
  `Constants.Variables` still exists.
- Check that `runtime*.tab` (used by the MSL converter, see
  [logging.md](logging.md)) still matches `rtoffsets`.
- Run `tools/calconv/test.py`. It asserts layout counts. Then look at the
  database warnings of `calconv plan` for contradictions, overlaps and
  duplicates (see [calibration-converter.md](calibration-converter.md)).
