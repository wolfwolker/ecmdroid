# egotune - narrowband fuel-map tuning for EcmDroid
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, see <http://www.gnu.org/licenses/>.
"""Runtime data: channel definitions from the database, and EcmDroid .bin logs.

The .bin format is described in docs/logging.md: a 5-byte ECM ID, then
records of a 4-byte big-endian timestamp (1/100 s) and one complete runtime
response frame. Channel offsets are relative to that frame (table rtoffsets),
values are little-endian, physical = raw * scale + translate.
"""

from __future__ import annotations

import gzip
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path


class LogError(Exception):
    """A log can't be read or doesn't fit the ECM definitions."""


@dataclass(frozen=True)
class Channel:
    name: str
    size: int
    offset: int
    scale: float
    translate: float


@dataclass
class RuntimeDefs:
    """The runtime channels of one ECM ID."""

    ecm_id: str
    frame_len: int
    channels: dict[str, Channel]

    def has(self, name: str) -> bool:
        return name in self.channels

    def raw(self, frame: bytes, name: str) -> int:
        ch = self.channels[name]
        return int.from_bytes(frame[ch.offset:ch.offset + ch.size], "little")

    def value(self, frame: bytes, name: str) -> float:
        ch = self.channels[name]
        return self.raw(frame, name) * ch.scale + ch.translate

    def bit(self, frame: bytes, name: str, bit: int) -> bool:
        return bool(self.raw(frame, name) >> bit & 1)


def load_runtime_defs(db_path: Path | str, ecm_id: str) -> RuntimeDefs:
    raw = Path(db_path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    con = sqlite3.connect(":memory:")
    try:
        con.deserialize(raw)
        row = con.execute("SELECT category, poll_len FROM eeprom WHERE name = ?", (ecm_id,)).fetchone()
        if row is None:
            raise LogError(f"unknown ECM ID {ecm_id!r}")
        category, frame_len = row
        channels = {}
        for name, size, offset, scale, translate in con.execute(
                "SELECT varname, size, offset, scale, translate FROM rtoffsets "
                "WHERE category = ? ORDER BY uniqueid", (category,)):
            if offset + size <= frame_len:
                channels.setdefault(name, Channel(name, size, offset, float(scale or 1), float(translate or 0)))
    finally:
        con.close()
    return RuntimeDefs(ecm_id, frame_len, channels)


@dataclass(frozen=True)
class Record:
    time: float  # seconds since the recording started
    frame: bytes


@dataclass
class BinLog:
    path: Path | None
    ecm_id: str
    records: list[Record] = field(default_factory=list)
    bad_checksum: int = 0
    trailing_bytes: int = 0

    @property
    def name(self) -> str:
        return self.path.name if self.path else "log"

    @property
    def duration(self) -> float:
        return self.records[-1].time - self.records[0].time if len(self.records) > 1 else 0.0


def log_id(data: bytes) -> str:
    """The ECM ID a log was recorded with ("UNKWN" if the app didn't know it)."""
    if len(data) < 5:
        raise LogError("too short for an EcmDroid log")
    return data[:5].decode("ascii", "replace")


def checksum_ok(frame: bytes) -> bool:
    """XOR of bytes 1 .. n-2 equals the last byte (docs/protocol.md)."""
    x = 0
    for b in frame[1:-1]:
        x ^= b
    return x == frame[-1]


def parse_log(data: bytes, frame_len: int, path: Path | None = None) -> BinLog:
    log = BinLog(path, log_id(data))
    pos, step = 5, 4 + frame_len
    while pos + step <= len(data):
        t = int.from_bytes(data[pos:pos + 4], "big") / 100.0
        frame = data[pos + 4:pos + step]
        pos += step
        if checksum_ok(frame):
            log.records.append(Record(t, frame))
        else:
            log.bad_checksum += 1
    log.trailing_bytes = len(data) - pos
    return log


def read_log(path: Path | str) -> bytes:
    path = Path(path)
    try:
        return path.read_bytes()
    except OSError as e:
        raise LogError(f"can't read {path}: {e.strerror}") from e
