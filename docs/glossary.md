# Glossary & Related Software

## Terms

The labels in parentheses are the names the ECM database uses (`names.varname` /
`names.origname`), so you can find the matching variable in EcmDroid.

| Term                     | Meaning                                                                                                                                      |
|--------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| **DDFI / DDFI-2 / DDFI-3** | The three generations of Buell's fuel-injection ECM: DDFI on fuel-injected tube-frame models ("Tubers", 1999–2002), DDFI-2 on XB models 2003–2007, DDFI-3 on XB 2008+ and 1125R/CR. |
| **ECM**                  | Engine Control Module.                                                                                                                       |
| **ECM ID**               | First five characters of the version string the ECM reports (e.g. `BUEIB`). Selects the layout. See [supported-ecms.md](supported-ecms.md). |
| **P&A race ECM**         | Parts & Accessories race ECM. Uses the stock protocol (9600 baud). Usually has a printed "RACE USE ONLY" marking.                            |
| **Factory Race ECM**     | Race ECM with its own bus address `0x55` and 19200 baud. Usually has an engraved "RACE USE ONLY" marking.                                    |
| **EEPROM**               | Non-volatile ECM memory holding configuration, maps and learned values. See [eeprom.md](eeprom.md).                                          |
| **Page / page 0**        | EEPROM transfer unit (≤ 256 bytes). Page 0 is a small special page with stored errors, Baro, Front AFV and per-unit data (on DDFI-3: VIN, odometer, security, counters, manufacturing date and serial). On DDFI/DDFI-2 the manufacturing date and serial are in page 1. |
| **Firmware / calibration** | Firmware = the ECM's program, which defines the ECM ID and EEPROM layout (changed only by a dealer reflash). Calibration = the EEPROM content (`.xpr`), which EcmDroid can read and burn. See [supported-ecms.md](supported-ecms.md#ddfi-3-firmware-calibration-and-swapping-ecms). |
| **Fetch / Burn**         | Read the EEPROM from the ECM / write it back.                                                                                                |
| **XPR / EPR file**       | ECMSpy's EEPROM image files: `.xpr` = full image including page 0, `.epr` = without page 0. Both are raw bytes. See [eeprom.md](eeprom.md#eeprom-files-xpr). |
| **Runtime data / live data** | The block of current sensor values and states the ECM returns for the `'C'` request.                                                    |
| **AFV** (`LFuel`, `LFuel1`) | Adaptive Fuel Value ("Learned Fuel"), in percent. A correction the ECM learns from the O2 sensor in the Closed Loop Learn (and Open Loop Learn) regimes and applies in open loop and open-loop WOT. Rear cylinder (`LFuel`) and, on DDFI-3, front (`LFuel1`). |
| **EGO correction** (`FBFuel`, *EGO Corr.*) | Short-term closed-loop fuel correction from the exhaust gas oxygen sensor. The ECM still reports it in open loop, but frozen at the last closed-loop value and not applied. |
| **Closed loop / open loop** | Fuelling that does / doesn't use O2 sensor feedback. The MSL converter uses Flags2 bit 7 to tell them apart.                              |
| **O2 sensor**            | Narrow-band exhaust oxygen sensor. *O2 Sensor Target Voltage* (`KO2_Midpoint`) is the voltage the ECM aims for in closed loop.               |
| **WUE** (`CrTE`)         | Warm-up enrichment ("Engine Temp Correction").                                                                                               |
| **TPS / TPD / TPP**      | Throttle position sensor; throttle position in degrees / percent.                                                                            |
| **TPS reset**            | Re-learning the closed-throttle TPS position. Function `0x08` on DDFI/DDFI-2. Service manual procedure on DDFI-3.                            |
| **CLT** (`TE`)           | Engine (cylinder head) temperature.                                                                                                          |
| **MAT** (`TA`)           | Intake air temperature.                                                                                                                      |
| **MAP / ABP / Baro**     | Manifold absolute pressure / airbox pressure / barometric pressure. `KBaro` is the stored Baro Pressure Sensor value (page 0).                |
| **BAS**                  | Bank angle sensor (tip-over switch).                                                                                                         |
| **IAC**                  | Idle Air Control (stepper position, `IAC Pos.`).                                                                                             |
| **AMC**                  | Active Muffler Control, the exhaust valve actuator (`KAMC_Config`, *Exhaust Config* in Setup, active test *Exhaust Valve*).                  |
| **AIC / Active intake**  | Active intake actuator (`KAIC_Config`, `AIC_Count` = number of actuations).                                                                  |
| **Fuel map**             | Per-cylinder 2-D tables (`Tab_Fuel_Front`, `Tab_Fuel_Rear`) of base fuel over RPM and load (throttle-based) axes. EcmDroid shows them only as raw EEPROM bytes. Use ECMSpy Mono or TunerPro to edit maps. |
| **Spark / timing table** | 2-D ignition advance tables (`Tab_Spark_Front`, `Tab_Spark_Rear`).                                                                           |
| **DTC / trouble code**   | Diagnostic trouble code. *Current* errors come from live data (`CDiag*`), *stored* errors from live data (`HDiag*_LD`) or EEPROM (`HDiag*`). |
| **Error mask**           | EEPROM bits (`EDiag*`) that control which faults the ECM reports. Edited in Setup → Error Mask.                                              |
| **MSL**                  | MegaLogViewer log format (tab-separated text) that EcmDroid can produce from its binary logs.                                                |
| **WOT**                  | Wide-open throttle.                                                                                                                          |

Sources for the tuning terms: the ecmspy.com
[Tuning Guide](https://ecmspy.com/tgv2/guide2.shtml),
[error code list](https://ecmspy.com/errorcodes.shtml) and
[FAQ](https://ecmspy.com/faq.shtml).

## Related software

| Software                                                     | Platform                         | Relationship to EcmDroid                                                                                                                                                                                                 |
|--------------------------------------------------------------|----------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **[ecmspy.com](https://ecmspy.com)**                         | website                          | Home of the ECMSpy project and the main source of public knowledge about the DDFI ECMs: protocol ([EEPROM info](https://ecmspy.com/eeprom_info.shtml)), [runtime data layout](https://ecmspy.com/runtime.shtml), [error codes](https://ecmspy.com/errorcodes.shtml), [pinouts](https://ecmspy.com/pinouts.shtml), per-ECM EEPROM directories, a tuning guide and adapter articles. EcmDroid's database is derived from the ecmspy.com database. |
| **[EcmSpy for Mono](https://ecmspy.com/downloads.shtml)**    | Windows (.NET on Mono 2.10)      | **The reference desktop tool.** Live data, diagnostics, active tests, TPS reset (DDFI/DDFI-2), setup editors, static fuel/timing maps, log-based map analysis, EEPROM fetch/burn/load/save (`.xpr`/`.epr` files), wideband O2 logging. It **opens EcmDroid's binary `.bin` logs**. Last release 2.0.31.2 (2014-09-11). [User guide](https://ecmspy.com/ug_mono/V2.0/userguide_mono.shtml). |
| EcmSpy for Windows (original)                                | Windows                          | **Deprecated.** The original application (1.12.x) was withdrawn when that project ended, and it didn't support 2008+ (DDFI-3) motorcycles. Use EcmSpy for Mono instead and don't use the original as a reference. |
| EcmSpy for PalmOS                                            | PalmOS                           | Historic PDA version (GPL v2 source on ecmspy.com). Useful as a protocol reference. EcmSpy for Mono also reads its binary logs.                                                                                        |
| **[TunerPro / TunerPro RT](https://www.tunerpro.net)**       | Windows                          | Generic table editor and data logger. tunerpro.net provides an [XDF (bin definition) and ADX (data acquisition definition)](https://www.tunerpro.net/downloadBinDefs.htm) for each Buell ECM type, plus a Buell I/O plug-in installed with TunerPro RT. Known limitation: the XDFs don't cover page-0 (negative-offset) data. |
| **[MegaLogViewer](https://www.efianalytics.com/MegaLogViewer/)** | desktop                      | Log viewer for the `.msl` files that EcmDroid and EcmSpy write.                                                                                                                                                         |
| **[ecmsim](https://github.com/ecmdroid/ecmsim)**              | Java (desktop)                   | Simple ECM simulator over TCP for testing EcmDroid without a motorcycle. See [development.md](development.md#testing-without-a-motorcycle).                                                                             |

### Typical workflow

EcmDroid is the tool you carry on the bike: diagnostics, active tests, live
data, logging, quick setup changes, and EEPROM backups. Detailed map tuning is
done on a PC with EcmSpy for Mono (or TunerPro):

- Exchange EEPROM images as `.xpr` files.
- Analyse EcmDroid's `.bin` logs in EcmSpy for Mono, or its `.msl` logs in
  MegaLogViewer.
