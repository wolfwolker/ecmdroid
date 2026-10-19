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
"""From per-cell corrections to new fuel maps, and the new image.

new = old x (1 + gain x confidence x (correction / 100 - 1)), clamped to
max_rich/max_lean per iteration and rounded to the map's resolution.
confidence grows with the seconds of data in the cell, up to full_seconds.
Cells with less than min_seconds of data, and every cell of a cylinder
without closed-loop feedback, keep their value.
"""

from __future__ import annotations

from dataclasses import dataclass

from calconvlib.image import Image

from .analysis import Analysis, CylinderResult, Settings
from .fuelmap import encode_map

# Cell states
CHANGED = "changed"
CAPPED = "capped"  # changed, but limited by max_rich/max_lean
BELOW_RESOLUTION = "below resolution"  # the change rounds away
FEW_DATA = "too little data"
NO_DATA = "no data"
INACTIVE = "no feedback"


@dataclass
class CellChange:
    index: int
    old: float
    new: float
    correction: float | None  # mean correction in %, None without data
    seconds: float
    state: str
    saturated: str | None = None

    @property
    def percent(self) -> float:
        return 100.0 * (self.new / self.old - 1) if self.old else 0.0


@dataclass
class MapChanges:
    cylinder: str
    map_name: str
    cells: dict[int, CellChange]

    @property
    def changed(self) -> list[CellChange]:
        return [c for c in self.cells.values() if c.state in (CHANGED, CAPPED)]

    def values(self, old: list[float]) -> list[float]:
        out = list(old)
        for c in self.cells.values():
            out[c.index] = c.new
        return out


def propose(res: CylinderResult, settings: Settings) -> MapChanges:
    fmap = res.fuel_map
    cells = {}
    for idx in fmap.cells_in_use():
        old = fmap.values[idx]
        stat = res.cells.get(idx)
        seconds = stat.seconds if stat else 0.0
        corr = stat.mean if stat and seconds else None
        sat = stat.saturation(settings.saturated) if stat else None
        if not res.active:
            cells[idx] = CellChange(idx, old, old, corr, seconds, INACTIVE)
            continue
        if corr is None:
            cells[idx] = CellChange(idx, old, old, None, 0.0, NO_DATA)
            continue
        if seconds < settings.min_seconds:
            cells[idx] = CellChange(idx, old, old, corr, seconds, FEW_DATA, sat)
            continue
        confidence = min(1.0, seconds / settings.full_seconds)
        factor = 1 + settings.gain * confidence * (corr / 100.0 - 1)
        lo, hi = 1 - settings.max_lean / 100.0, 1 + settings.max_rich / 100.0
        capped = not lo <= factor <= hi
        factor = min(hi, max(lo, factor))
        new = float(round(old * factor))
        # Never cross the cap through rounding.
        while new > old * hi + 1e-9:
            new -= 1
        while new < old * lo - 1e-9:
            new += 1
        if new == old:
            state = BELOW_RESOLUTION
        else:
            state = CAPPED if capped else CHANGED
        cells[idx] = CellChange(idx, old, new, corr, seconds, state, sat)
    return MapChanges(res.cylinder.key, res.cylinder.map_name, cells)


def propose_all(analysis: Analysis) -> dict[str, MapChanges]:
    return {k: propose(r, analysis.settings) for k, r in analysis.cylinders.items()}


class VerifyError(Exception):
    """The new image isn't exactly the old one with the new maps."""


def build_image(img: Image, changes: dict[str, MapChanges]) -> bytes:
    """The input image with only the fuel-map bytes replaced, verified."""
    data = bytearray(img.data)
    ranges = []
    expected = {}
    for ch in changes.values():
        var = img.var(ch.map_name)
        start = img.start(var)
        values = ch.values(img.physical(var))
        data[start:start + var.size] = encode_map(img, ch.map_name, values)
        ranges.append((start, start + var.size))
        expected[ch.map_name] = values
    out = bytes(data)

    check = Image(img.ecm_id, img.layout, out, None)
    for name, values in expected.items():
        if check.physical(check.var(name)) != values:
            raise VerifyError(f"{name}: the written map doesn't read back as computed")
    for i, (a, b) in enumerate(zip(img.data, out)):
        if a != b and not any(lo <= i < hi for lo, hi in ranges):
            raise VerifyError(f"byte {i} outside the fuel maps changed")
    if len(out) != len(img.data):
        raise VerifyError("the image size changed")
    return out
