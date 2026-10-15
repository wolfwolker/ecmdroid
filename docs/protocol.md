# ECM Serial Protocol

This page describes the DDFI diagnostic protocol as EcmDroid implements it
(`org.ecmdroid.PDU` and `org.ecmdroid.ECM`). It's the protocol ECMSpy uses.
The upstream description is ecmspy.com's
[EEPROM info page](https://ecmspy.com/eeprom_info.shtml), and the GPL v2
sources of *EcmSpy for PalmOS* linked from there are a further reference.

Where ecmspy.com and EcmDroid differ, EcmDroid's behaviour (and its test
vectors in `TestPDU`) is what works against real ECMs:

- ecmspy.com describes *Data Size* as "Number of Bytes from SOT incl. EOT", but
  its own examples count the bytes **after** SOT up to and including EOT.
- The checksum of ecmspy.com's example *response* frame (`0xE0`) doesn't match
  the XOR rule, while its request examples (`0xEB`, `0xCF`, `0xE8`) do.

## Physical link

The ECM exposes an asynchronous serial line on the diagnostic connector. It
uses **TTL levels** (logical 0 < 0.8 V, logical 1 > 2.0 V), and ecmspy.com
warns that the voltage must never exceed 5.0 V. EcmDroid never talks to the ECM
directly; it always goes through an adapter that turns this line into a byte
stream:

| Transport                | Implementation                                  | Notes                                                                                                                         |
|--------------------------|-------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Classic Bluetooth (SPP)  | `ECM.connect(BluetoothDevice, Protocol)`         | RFCOMM socket with the SPP UUID `00001101-0000-1000-8000-00805F9B34FB`. Must be paired in Android settings first.              |
| Bluetooth Low Energy     | `ECM.connect(Context, BluetoothDevice, Protocol)` | Vendored `SerialSocket` (Kai Morich). Supports TI CC254x, Nordic nRF UART, Microchip RN4870/1 and Telit TIO serial profiles. |
| USB-to-serial            | `ECM.connect(UsbSerialPort, Protocol)`           | [usb-serial-for-android](https://github.com/mik3y/usb-serial-for-android): FTDI, Silabs CP210x, Prolific PL2303, CH34x, CDC-ACM. |
| TCP/IP                   | `ECM.connect(String host, int port, Protocol)`   | Raw byte stream, 5 s connect timeout. Used with [ecmsim](https://github.com/ecmdroid/ecmsim) or a WiFi-to-serial bridge.        |

Line settings are **8N1, no handshake**:

| ECM protocol (`ECM.Protocol`) | Baud rate | ECM address |
|-------------------------------|-----------|-------------|
| `STOCK` ("Stock / P&A")       | 9600      | `0x42`      |
| `FACTORY_RACE` ("Factory Race") | 19200   | `0x55`      |

With USB adapters EcmDroid sets the baud rate itself
(`MainActivity.findCOMDevice()`). Bluetooth adapters must already be configured
for the right speed, and TCP bridges likewise.

## Frame (PDU) format

Every request and response uses the same frame:

| Offset   | Size  | Field        | Value / meaning                                                                         |
|----------|-------|--------------|-----------------------------------------------------------------------------------------|
| 0        | 1     | SOH          | `0x01`                                                                                  |
| 1        | 1     | Sender       | `0x00` = tester (EcmDroid), `0x42` = stock/P&A ECM, `0x55` = factory race ECM           |
| 2        | 1     | Recipient    | as above                                                                                |
| 3        | 1     | Length `N`   | number of bytes from offset 6 up to **and including** EOT                               |
| 4        | 1     | EOH          | `0xFF`                                                                                  |
| 5        | 1     | SOT          | `0x02`                                                                                  |
| 6        | `N-1` | Body         | request: command byte + arguments; response: status byte + data                        |
| `5+N`    | 1     | EOT          | `0x03`                                                                                  |
| `6+N`    | 1     | Checksum     | XOR of all bytes from offset 1 (sender) through EOT                                     |

The total frame length is `N + 7`. The checksum excludes SOH and the checksum
byte itself (`PDU.checksum()`).

In a response, the first body byte (offset 6) is the status: `0x06` (ACK) on
success, otherwise an error indicator. `ECM.sendPDU()` throws an `IOException`
if the sender isn't the configured ECM address ("wrong Protocol?") or the status
isn't ACK. Response data starts at offset 7 and has `N - 2` bytes
(`PDU.getEEPromData()`).

### Worked examples

These frames come from `TestPDU`:

```
Read 16 bytes, page 1, offset 0
01 00 42 05 FF 02 | 52 00 01 10 | 03 FA
                    R  off pg cnt

Run active test "Fan" (function 9)
01 00 42 05 FF 02 | 57 00 20 09 | 03 C7
                    W  off pg fn

Version response from a BUEIB (17 ASCII chars: "BUEIB310 12-11-03")
01 42 00 13 FF 02 | 06 42 55 45 49 42 33 31 30 20 31 32 2D 31 31 2D 30 33 | 03 E2
                    ACK
```

## Commands

| Command        | Body bytes                         | Response data                                                | EcmDroid method                         |
|----------------|------------------------------------|--------------------------------------------------------------|-----------------------------------------|
| Get version    | `56` (`'V'`)                       | ASCII version string, e.g. `BUEIB310 12-11-03`               | `ECM.readVersion()`                     |
| Runtime data   | `43` (`'C'`)                       | Live data block (see below)                                  | `ECM.readRTData()`                      |
| Read EEPROM    | `52 offset page count` (`'R'`)     | `count` bytes                                                | `ECM.readEEPromPage()`                  |
| Write EEPROM   | `57 offset page data…` (`'W'`)     | none (ACK only)                                              | `ECM.writeEEPromPage()`                 |
| Run function   | `57 00 20 code`                    | none (ACK only)                                              | `ECM.runTest(Function)`                 |
| Get busy state | `52 00 20 01`                      | 1 byte: `0` = idle, anything else = busy                     | `ECM.getCurrentState()` / `isBusy()`    |

Notes:

- **Offset and page are both single bytes**, so a page is at most 256 bytes.
  EcmDroid transfers at most **16 bytes per read/write request**.
- **Page `0x20` (32) is a virtual page**, not EEPROM. Writing a function code
  to offset 0 triggers a function. Reading the same location returns the ECM
  status (`0x00` = normal, anything else = busy). `ActiveTestsFragment` polls it
  every 500 ms until the test has finished.
- A write (`W`) is answered with an ACK and no data (body `06 03`).
- The first 5 characters of the version string are the **ECM ID** (e.g.
  `BUEIB`). The ID selects the EEPROM layout and variable definitions from the
  database (see [database.md](database.md)).

### Function codes (`PDU.Function`)

| Code   | Function       | Exposed in UI                              |
|--------|----------------|--------------------------------------------|
| `0x01` | Clear codes    | Trouble Codes → *Clear*                    |
| `0x02` | Front coil     | Active Tests                               |
| `0x03` | Rear coil      | Active Tests                               |
| `0x04` | Tachometer     | Active Tests                               |
| `0x05` | Fuel pump      | Active Tests                               |
| `0x06` | Front injector | Active Tests                               |
| `0x07` | Rear injector  | Active Tests                               |
| `0x08` | TPS reset      | Active Tests → *TPS Reset* (not on DDFI-3) |
| `0x09` | Fan            | Active Tests                               |
| `0x0A` | Exhaust valve  | Active Tests                               |
| `0x0B` | Active intake  | Active Tests                               |
| `0x0C` | Shift light    | Active Tests                               |

ecmspy.com documents codes `0x01`–`0x0A`. Codes `0x0B` and `0x0C` come from
EcmDroid's `PDU.Function`. On DDFI-3 ECMs the app doesn't send the TPS reset;
it tells the user to follow the service manual instead.

## Runtime data block

`ECM.readRTData()` stores and returns the **complete response frame**, not just
the payload. (The method's Javadoc says "payload only", which is wrong.) All
runtime variable offsets in the database and in the `runtime*.tab` files are
relative to the start of the frame:

- offset 0–5: frame header (`01 42 00 LEN FF 02`)
- offset 6: status (`06` = ACK)
- offset 7…: live data, starting with `KConfig_LD` (System Configuration)
- last two bytes: EOT, checksum

The database models the header bytes as *secret* runtime variables (`SOH`,
`Source`, `Destination`, `Len`, `EOH`, `SOT`, `ACK` at offsets 0–6). Because
they're secret, the UI never lists them.

The frame size is fixed per ECM family. The database stores it as
`eeprom.poll_len`:

| Family / categories             | Frame size | Examples                               |
|---------------------------------|-----------:|----------------------------------------|
| DDFI (categories 3–5)           | 99 bytes   | BUEGC, BUEJA, BUEKA (BUEIA: 100)       |
| DDFI-2 (category 6)             | 103 bytes  | BUECB                                  |
| DDFI-2 (categories 7–9)         | 107 bytes  | BUEGB, BUEIB, BUEIC, B2RIB             |
| DDFI-3 (categories 49–90)       | 135 bytes  | BUE1D/2D/3D, BUEOD/WD/YD/ZD, B3Rx      |

Multi-byte values are **little-endian**. A physical value is
`raw × scale + translate` (see [database.md](database.md#value-conversion)).

## Receive logic and error handling

`ECM.receivePDU()` reads the 6-byte header, takes `N` from offset 3, then reads
`N + 1` more bytes. Each stage has a 1 s timeout (`DEFAULT_TIMEOUT`, polled in
10 ms steps). The frame is then checked for markers, length and checksum
(`PDU.validate()`). If anything fails, the input stream is drained so that the
next exchange starts in sync, and an `IOException` is thrown.

`ECM.sendPDU()` is `synchronized`. The UI tasks and the background reader
thread of `EcmDroidService` share one link, and requests never interleave.

## Address selection

`PDU.setProtocol()` sets a **static, process-wide** ECM address and rebuilds
the cached version, runtime data and state requests. Every `connect(...)`
overload calls it, so the protocol is fixed for the lifetime of a connection.
The *Protocol* spinner on the ECM Information screen is disabled while
connected.
