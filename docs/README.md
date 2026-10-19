# EcmDroid Documentation

| Document                                   | For        | Contents                                                                                  |
|--------------------------------------------|------------|-------------------------------------------------------------------------------------------|
| [User guide](user-guide.md)                | riders     | Adapters, connecting, every screen, settings, troubleshooting                             |
| [Narrowband fuel-map tuning](tuning.md)    | riders     | Tuning the closed-loop fuel maps of a DDFI-3 with the stock O2 sensors: lock the AFV, log, apply the corrections, iterate. By hand or with the offline [`egotune`](../tools/egotune/README.md) tool (in testing) |
| [Supported ECMs](supported-ecms.md)        | everyone   | ECM IDs, families, stock vs P&A vs Factory Race, feature availability                     |
| [Glossary & related software](glossary.md) | everyone   | Buell/DDFI terminology, ecmspy.com, ECMSpy Mono, TunerPro, MegaLogViewer                  |
| [Architecture](architecture.md)            | developers | Components, flows, threading, Setup-screen DSL, preferences, permissions                  |
| [Protocol](protocol.md)                    | developers | Serial link, frame format, checksum, commands, function codes, runtime data block         |
| [EEPROM](eeprom.md)                        | developers | Pages, page 0, in-memory image, fetch/edit/burn, `.xpr` files                             |
| [Database](database.md)                    | developers | Bundled ecmspy.com SQLite DB: schema, lookups, value conversion, updating it              |
| [Live data & logging](logging.md)          | developers | Polling service, binary log format, MSL conversion, trouble-code decoding                 |
| [Development](development.md)              | developers | Build, signing, tests, simulator, conventions, releasing, known issues                    |
| [How calconv works](calibration-converter-overview.md) | everyone | One-page overview of the calibration converter: what it copies or keeps, what the TOML rule files are, and who writes and approves them |
| [Moving a tune to another ECM](calibration-converter-howto.md) | riders | How to carry a tune to an ECM with another firmware ID (e.g. BUE2D → BUEYD) with the offline `calconv` tool, how to read its report, and how to help test it (in testing: don't burn its results yet) |
| [Calibration converter](calibration-converter.md) | developers | Plan, rules and status of the offline tool (`tools/calconv`) that compares and converts tunes between firmware layouts (first case BUE2D → BUEYD) |
