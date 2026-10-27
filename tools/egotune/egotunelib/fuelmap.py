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
"""DDFI-2/DDFI-3 fuel maps: Tab_Fuel_Front/Tab_Fuel_Rear over RPM x load.

A map is stored row by row: one row per load breakpoint, one column per RPM
breakpoint. On DDFI-2 each row ends with `skip` (1) unused bytes, so a row
is cols + skip bytes long (index = row * (cols + skip) + col); the BUEIB test
log confirms this layout. Axes can be stored in descending order, and
unused breakpoints at the end are zero (the BUE2D test image uses 17 of its
20 RPM columns, the BUEIB one 12 of 13), so only the used part is addressed.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from calconvlib.image import Image, element_ints, encode_element, physical_values

MAPS = ("Tab_Fuel_Front", "Tab_Fuel_Rear")
FAMILIES = ("DDFI-2", "DDFI-3")  # checked against real logs; DDFI-1 isn't


class MapError(Exception):
    """A fuel map or its axes can't be used."""


@dataclass(frozen=True)
class Axis:
    name: str
    values: list[float]  # all stored breakpoints
    used: int  # number of breakpoints in use, from index 0

    def __post_init__(self):
        pts = self.values[:self.used]
        ascending = all(a < b for a, b in zip(pts, pts[1:]))
        descending = all(a > b for a, b in zip(pts, pts[1:]))
        if self.used < 2 or not (ascending or descending):
            raise MapError(f"{self.name}: breakpoints {pts} aren't strictly monotonic")
        # (value, storage index), ascending by value
        object.__setattr__(self, "_sorted", sorted((v, i) for i, v in enumerate(pts)))

    def weights(self, x: float) -> list[tuple[int, float]]:
        """Storage indexes and linear-interpolation weights for x, clamped at the ends."""
        pts = self._sorted
        if x <= pts[0][0]:
            return [(pts[0][1], 1.0)]
        if x >= pts[-1][0]:
            return [(pts[-1][1], 1.0)]
        k = bisect_right([v for v, _ in pts], x) - 1
        (v0, i0), (v1, i1) = pts[k], pts[k + 1]
        f = (x - v0) / (v1 - v0)
        return [(i0, 1.0 - f), (i1, f)] if f > 0 else [(i0, 1.0)]

    def order(self) -> list[int]:
        """Storage indexes in ascending breakpoint order (for display)."""
        return [i for _, i in self._sorted]


def make_axis(name: str, values: list[float]) -> Axis:
    used = len(values)
    while used > 0 and values[used - 1] == 0:
        used -= 1
    return Axis(name, list(values), used)


@dataclass
class FuelMap:
    name: str
    cols: int
    rows: int
    rpm: Axis  # columns
    load: Axis  # rows
    values: list[float]  # physical values as stored, row by row, including skipped bytes
    skip: int = 0  # unused bytes at the end of each row

    @property
    def stride(self) -> int:
        return self.cols + self.skip

    def index(self, row: int, col: int) -> int:
        return row * self.stride + col

    def cells_in_use(self) -> list[int]:
        return [self.index(r, c) for r in range(self.load.used) for c in range(self.rpm.used)]

    def cell_weights(self, rpm: float, load: float) -> list[tuple[int, float]]:
        """Bilinear weights of the (up to four) cells around an operating point."""
        return [(self.index(r, c), wr * wc)
                for r, wr in self.load.weights(load)
                for c, wc in self.rpm.weights(rpm)]

    def lookup(self, rpm: float, load: float) -> float:
        return sum(self.values[i] * w for i, w in self.cell_weights(rpm, load))

    def row_col(self, index: int) -> tuple[int, int]:
        return divmod(index, self.stride)


def load_fuel_map(img: Image, name: str) -> FuelMap:
    var = img.var(name)
    if img.layout.family not in FAMILIES or var is None or var.type != "Map":
        raise MapError(f"{img.ecm_id} has no fuel map {name} (egotune supports DDFI-2 and DDFI-3 ECMs)")
    xname, yname = img.layout.axis_refs(var)
    if not xname or not yname:
        raise MapError(f"{name}: axis variables missing in the database")
    rpm = make_axis(xname, img.physical(img.var(xname)))
    load = make_axis(yname, img.physical(img.var(yname)))
    skip = var.skip or 0
    if var.cols != len(rpm.values) or var.rows != len(load.values) or var.count != (var.cols + skip) * var.rows:
        raise MapError(f"{name}: {var.cols}x{var.rows} cells (+{skip} per row) don't match its axes "
                       f"({len(rpm.values)} x {len(load.values)} breakpoints) or its {var.count} elements")
    return FuelMap(name, var.cols, var.rows, rpm, load, img.physical(var), skip)


def encode_map(img: Image, name: str, values: list[float]) -> bytes:
    """The raw bytes for a map with new physical values (MapError if one doesn't fit)."""
    var = img.var(name)
    ints = []
    for i, v in enumerate(values):
        raw = encode_element(var, i, v)
        if raw is None:
            raise MapError(f"{name}: value {v} at cell {i} doesn't fit {var.width} byte(s)")
        ints.append(raw)
    data = b"".join(n.to_bytes(var.width, "little") for n in ints)
    # Same values back, apart from rounding to the stored resolution.
    back = physical_values(var, data)
    if element_ints(var, data) != ints or len(back) != len(values):
        raise MapError(f"{name}: encoding check failed")
    return data
