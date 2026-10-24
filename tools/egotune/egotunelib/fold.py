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
"""Fold the learned AFV into the fuel maps (docs/egotune-howto.md, step 2).

The ECM applies the AFV in open loop instead of the EGO correction. Before
tuning, every used cell of a map is multiplied by its cylinder's AFV and the
AFV is set to 100 %, so the fuelling stays the same while the AFV starts
again from 100 % (ECMSpy Mono's tuning method). Setting the AFV to 100 %
without folding it in would change the open-loop and WOT fuelling by the
same amount.

DDFI-2 has one AFV (LFuel) for both maps. DDFI-3 has LFuel for the rear and
LFuel1 for the front; LFuel1 lives in page 0, so it needs an .xpr. A layout
without LFuel1 uses LFuel for both maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from calconvlib.image import Image, element_scale, encode_element, pack_ints

from .fuelmap import MapError, encode_map, load_fuel_map
from .report import TESTING_NOTE
from .tune import VerifyError

LARGE = 10.0  # % away from 100 that deserves a look at the causes outside the maps


def _value(img: Image, name: str) -> float | None:
    v = img.value_of(name) if img.var(name) else None
    return None if v is None else round(v, 3)  # 0.1 % steps, without float noise


@dataclass
class Fold:
    map_name: str
    afv_name: str
    afv: float
    old: list[float]
    new: list[float]

    @property
    def changed(self) -> list[int]:
        return [i for i, (a, b) in enumerate(zip(self.old, self.new)) if a != b]


def plan_fold(img: Image) -> list[Fold]:
    if img.var("LFuel") is None:
        raise MapError(f"{img.ecm_id} has no AFV (LFuel)")
    front_afv = "LFuel"
    if img.var("LFuel1") is not None:
        if not img.available(img.var("LFuel1")):
            raise MapError("the front AFV (LFuel1) is in page 0, which this image doesn't have: use the .xpr")
        front_afv = "LFuel1"
    folds = []
    for map_name, afv_name in (("Tab_Fuel_Front", front_afv), ("Tab_Fuel_Rear", "LFuel")):
        fmap = load_fuel_map(img, map_name)
        var = img.var(map_name)
        scale, translate = element_scale(var, 0)
        top = ((1 << (8 * var.width)) - 1) * scale + translate
        afv = _value(img, afv_name)
        new = list(fmap.values)
        for i in fmap.cells_in_use():
            new[i] = float(round(fmap.values[i] * afv / 100.0))
            if new[i] > top:
                # Capping it would make the engine leaner there than it runs now, at high load.
                row, col = fmap.row_col(i)
                raise MapError(
                    f"{map_name}: the cell at load {fmap.load.values[row]:g} / {fmap.rpm.values[col]:g} rpm "
                    f"would be {new[i]:g} with the AFV of {afv:g} %, above the map's maximum of {top:g}. The "
                    "AFV can't be folded in. Tune with it as it is: egotune's corrections don't depend on it.")
        folds.append(Fold(map_name, afv_name, afv, list(fmap.values), new))
    return folds


def warnings_for(img: Image, folds: list[Fold]) -> list[str]:
    out = []
    lo, hi = _value(img, "KLFuel_Min"), _value(img, "KLFuel_Max")
    for name in dict.fromkeys(f.afv_name for f in folds):
        afv = _value(img, name)
        if afv != 100 and lo is not None and afv in (lo, hi):
            out.append(f"{name} is {afv:g} %, at its learning limit ({lo:g}–{hi:g} %): the ECM wanted to "
                       "go further. Something outside the maps is likely off.")
        if abs(afv - 100) > LARGE:
            out.append(f"{name} is {afv:g} %, more than {LARGE:g} % away from 100 %. Rule out leaks, a faulty "
                       "O2 sensor, timing and the TPS setting first (docs/egotune-howto.md, *Before you "
                       "start*): folding them into the maps would hide them.")
    return out


def build_fold_image(img: Image, folds: list[Fold]) -> bytes:
    """The input image with the folded maps and the AFV at 100 %, verified."""
    data = bytearray(img.data)
    ranges = []
    for f in folds:
        var = img.var(f.map_name)
        start = img.start(var)
        data[start:start + var.size] = encode_map(img, f.map_name, f.new)
        ranges.append((start, start + var.size))
    for name in dict.fromkeys(f.afv_name for f in folds):
        var = img.var(name)
        start = img.start(var)
        data[start:start + var.size] = pack_ints(var, [encode_element(var, 0, 100.0)])
        ranges.append((start, start + var.size))
    out = bytes(data)

    check = Image(img.ecm_id, img.layout, out, None)
    for f in folds:
        if check.physical(check.var(f.map_name)) != f.new:
            raise VerifyError(f"{f.map_name}: the written map doesn't read back as computed")
        if _value(check, f.afv_name) != 100:
            raise VerifyError(f"{f.afv_name}: doesn't read back as 100 %")
    for i, (a, b) in enumerate(zip(img.data, out)):
        if a != b and not any(lo <= i < hi for lo, hi in ranges):
            raise VerifyError(f"byte {i} outside the fuel maps and the AFV changed")
    if len(out) != len(img.data):
        raise VerifyError("the image size changed")
    return out


def markdown(img: Image, folds: list[Fold], warnings: list[str], image: Path, out: Path | None) -> str:
    lines = [f"# Fold the AFV into the fuel maps: {img.ecm_id}", "", f"> **{TESTING_NOTE}**", "",
             f"- Image: `{image}`"]
    if out:
        lines.append(f"- Result: `{out}`")
    elif all(f.afv == 100 for f in folds):
        lines.append("- Nothing to fold: the AFV is already 100 %. Nothing was written.")
    lines += ["", "| Map | AFV | Cells changed | Smallest → largest change |", "|---|---|---|---|"]
    for f in folds:
        steps = [b - a for a, b in zip(f.old, f.new) if a != b]
        span = f"{min(steps):+g} → {max(steps):+g}" if steps else "–"
        lines.append(f"| `{f.map_name}` | {f.afv:g} % (`{f.afv_name}`) | {len(f.changed)} | {span} |")
    lines.append("")
    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]
    if out:
        lines += ["## Next steps", "",
                  f"1. Compare: `calconv diff {image} {out}` lists exactly what changed (the fuel maps and "
                  "the AFV).",
                  "2. Burn the result with EcmDroid, then *Fetch* the EEPROM again, check that the AFV is "
                  "exactly 100 % and save it (e.g. `iter0.xpr`).",
                  "3. Tune from that image, and pass it as `--baseline` in every round.", ""]
    return "\n".join(lines)
