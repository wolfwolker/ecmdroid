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
"""Shared fixtures: the app's BUE2D test image and log, and synthetic logs."""

from functools import lru_cache

import egotunelib  # noqa: F401  (puts calconvlib on the path)
from calconvlib.db import DEFAULT_DB, REPO_ROOT, Database
from calconvlib.image import load_image
from egotunelib.runtime import RuntimeDefs, load_runtime_defs, parse_log

FIXTURES = REPO_ROOT / "app" / "src" / "androidTest" / "resources"
BUE2D_IMAGE = FIXTURES / "BUE2D.eeprom"  # .xpr, 3796 bytes
BUE2D_LOG = FIXTURES / "BUE2D_log.bin"  # 2153 records, cold engine
BUEIB_IMAGE = FIXTURES / "BUEIB.eeprom"  # DDFI-2 .epr, 1206 bytes: the maps that were in the ECM for...
BUEIB_LOG = FIXTURES / "BUEIB_log.bin"  # ...this 42-minute warm ride (13982 records)

# In the BUE2D test image: rear map row 5 (load 30), column 6 (3400 rpm) = 45
ROW_30, COL_3400 = 5, 6


@lru_cache(maxsize=None)
def db() -> Database:
    return Database()


@lru_cache(maxsize=None)
def defs() -> RuntimeDefs:
    return load_runtime_defs(DEFAULT_DB, "BUE2D")


def image():
    return load_image(db(), BUE2D_IMAGE, "BUE2D")


# A warm, steady, closed-loop record with no correction.
BASE = {
    "RPM": 3400, "FLoad": 30, "RLoad": 30, "TE": 90.0, "CrTE": 100.0, "CrAcc": 0.0,
    "FBFuel": 100.0, "FBFuel1": 100.0, "LFuel_LD": 100.0, "LFuel1_LD": 100.0,
    "Flags1": 0b00000001, "Flags2": 0b10000000,
}


def frame(**values) -> bytes:
    d = defs()
    buf = bytearray(d.frame_len)
    buf[0] = 0x01
    for name, value in {**BASE, **values}.items():
        ch = d.channels[name]
        raw = round((value - ch.translate) / ch.scale)
        buf[ch.offset:ch.offset + ch.size] = raw.to_bytes(ch.size, "little")
    x = 0
    for b in buf[1:-1]:
        x ^= b
    buf[-1] = x
    return bytes(buf)


def log_bytes(frames, step: float = 0.2, ecm_id: str = "BUE2D") -> bytes:
    out = bytearray(ecm_id.encode("ascii"))
    for i, f in enumerate(frames):
        out += round(i * step * 100).to_bytes(4, "big") + f
    return bytes(out)


def steady(seconds: float, step: float = 0.2, **values) -> list[bytes]:
    return [frame(**values) for _ in range(round(seconds / step))]


def make_log(frames, step: float = 0.2):
    return parse_log(log_bytes(frames, step), defs().frame_len)


def ride(seconds: float, points=((3400, 30),), step: float = 0.2, ego=100.0, **values) -> list[bytes]:
    """A healthy warm closed-loop ride: the O2 sensor switches rich/lean about
    2.5 times a second, the front EGO correction moves around the rear one,
    and the logged table fuel is the image's own lookup (x 37.5, as on DDFI-2).
    Each operating point gets an equal share of the time; `ego` is the rear
    EGO correction, or a function of the record number."""
    from egotunelib.fuelmap import load_fuel_map
    img = image()
    front, rear = load_fuel_map(img, "Tab_Fuel_Front"), load_fuel_map(img, "Tab_Fuel_Rear")
    n = round(seconds / step)
    per_point = max(1, n // len(points))
    frames = []
    for i in range(n):
        rpm, load = points[min(i // per_point, len(points) - 1)]
        e = ego(i) if callable(ego) else ego
        v = {"RPM": rpm, "FLoad": load, "RLoad": load, "FBFuel": e,
             "FBFuel1": e + (-1, 0, 1, 0)[i % 4],
             "Flags2": 0b11000000 if i % 4 < 2 else 0b10000000,
             "TabFuel1_Raw": round(front.lookup(rpm, load) * 37.5),
             "TabFuel2_Raw": round(rear.lookup(rpm, load) * 37.5)}
        v.update(values)
        frames.append(frame(**v))
    return frames
