# calconv - ECM calibration converter for EcmDroid
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
"""EEPROM images (.xpr / .epr files) and value decoding.

Decoding follows Variable.refreshValue() in the app: little-endian, unsigned,
size / elemsize elements, value = raw * scale + translate. See docs/eeprom.md.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from .db import Database, Layout, VarDef, id_order


class ImageError(Exception):
    """A file can't be read or doesn't fit an ECM layout."""


@dataclass
class Image:
    ecm_id: str
    layout: Layout
    data: bytes
    path: Path | None = None

    @property
    def has_page0(self) -> bool:
        return self.layout.page0_size > 0 and len(self.data) == self.layout.xsize

    @property
    def kind(self) -> str:
        return ".xpr" if len(self.data) == self.layout.xsize else ".epr"

    @property
    def name(self) -> str:
        return str(self.path) if self.path else self.ecm_id

    def available(self, var: VarDef) -> bool:
        """Page-0 variables are missing from images without page 0."""
        return not var.in_page0 or self.has_page0

    def start(self, var: VarDef) -> int:
        return var.offset if var.offset >= 0 else len(self.data) + var.offset

    def raw(self, var: VarDef) -> bytes | None:
        if not self.available(var):
            return None
        start = self.start(var)
        return self.data[start:start + var.size]

    def values(self, var: VarDef) -> list | None:
        """Values exactly as the app computes them (Variable.rawValues)."""
        raw = self.raw(var)
        return None if raw is None else app_values(var, raw)

    def physical(self, var: VarDef) -> list | None:
        """Physical values without the app's integer truncation.

        Tables alternate axis and data values; the axis positions use
        axisscale/axistranslate (the app shows them unscaled).
        """
        raw = self.raw(var)
        return None if raw is None else physical_values(var, raw)

    def var(self, name: str) -> VarDef | None:
        return self.layout.vars.get(name)

    def value_of(self, name: str):
        """First physical value of a variable, or None if missing."""
        var = self.var(name)
        vals = self.physical(var) if var else None
        return vals[0] if vals else None

    def same_layout_ids(self) -> list[str]:
        return [i for i in self.layout.ids if i != self.ecm_id]


def _ints(var: VarDef, raw: bytes) -> list[int]:
    w = var.width
    return [int.from_bytes(raw[i * w:(i + 1) * w], "little") for i in range(var.count)]


def _string(raw: bytes, errors: str = "replace") -> str:
    end = raw.find(b"\0")
    return raw[:end if end >= 0 else len(raw)].decode("utf-8", errors)


def app_values(var: VarDef, raw: bytes) -> list:
    if var.type == "String":
        return [_string(raw)]
    ints = _ints(var, raw)
    if var.type == "Bits":
        return [v & 0xFFFF for v in ints]
    out = []
    for v in ints:
        x = float(v)
        if var.scale:
            x *= var.scale
        if var.translate:
            x += var.translate
        out.append(int(x) if var.fmt == "0" else x)
    return out


def physical_values(var: VarDef, raw: bytes) -> list:
    if var.type == "String":
        return [_string(raw, "backslashreplace")]  # keep invalid bytes visible and comparable
    if var.type == "Bits":
        return app_values(var, raw)
    out = []
    for i, v in enumerate(_ints(var, raw)):
        scale, translate = element_scale(var, i)
        if scale == 1.0 and not translate:
            out.append(v)  # exact, also for 8-byte values such as KVIN
        else:
            out.append(v * scale + translate)
    return out


def element_ints(var: VarDef, raw: bytes) -> list[int]:
    """The raw (unscaled) elements of a variable."""
    return _ints(var, raw)


def element_scale(var: VarDef, index: int) -> tuple[float, float]:
    """Scale and translate of one element (the axis half of tables differs)."""
    if var.type == "Table" and index % 2 == 0:
        scale, translate = var.axisscale, var.axistranslate
    else:
        scale, translate = var.scale, var.translate
    return scale or 1.0, translate or 0.0


def encode_element(var: VarDef, index: int, value: float) -> int | None:
    """The raw integer closest to a physical value, or None if it doesn't fit
    the element width (values are unsigned, as in the app)."""
    scale, translate = element_scale(var, index)
    raw = round((value - translate) / scale)
    return raw if 0 <= raw < 1 << (8 * var.width) else None


def pack_ints(var: VarDef, ints: list[int]) -> bytes:
    return b"".join(i.to_bytes(var.width, "little") for i in ints)


def decimals(fmt: str | None) -> int:
    if not fmt or "." not in fmt:
        return 0
    return len(fmt.split(".", 1)[1])


def scale_decimals(scale: float | None, limit: int = 3) -> int:
    """Decimals needed to show multiples of `scale` exactly (0.25 -> 2)."""
    if not scale:
        return 0
    for d in range(limit + 1):
        x = scale * 10 ** d
        if abs(x - round(x)) < 1e-6:
            return d
    return limit


def format_value(var: VarDef, value, index: int = 0) -> str:
    """Format like the database's display format, but never hide the
    fraction of a scaled value. Many variables combine format "0" with a
    scale such as 0.25, which the app shows truncated."""
    if value is None:
        return "–"
    if var.type == "Bits":
        return format(value, "08b")
    if isinstance(value, str):
        return value
    axis = var.type == "Table" and index % 2 == 0
    fmt_dec = decimals(var.axisformat if axis else var.fmt)
    dec = max(fmt_dec, scale_decimals(var.axisscale if axis else var.scale))
    text = f"{value:.{dec}f}"
    if dec > fmt_dec:
        whole, frac = text.split(".")
        frac = frac[:fmt_dec] + frac[fmt_dec:].rstrip("0")
        text = whole + ("." + frac if frac else "")
    return text[1:] if text.startswith("-") and float(text) == 0 else text


def format_values(var: VarDef, values: list | None) -> str:
    """A compact, human-readable form of all values of a variable."""
    if values is None:
        return "–"
    parts = [format_value(var, v, i) for i, v in enumerate(values)]
    if var.type == "Table":
        return ", ".join(f"{parts[i]}→{parts[i + 1]}" for i in range(0, len(parts) - 1, 2))
    return ", ".join(parts)


def load_image(db: Database, path: Path | str, ecm_id: str | None = None) -> Image:
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as e:
        raise ImageError(f"can't read {path}: {e.strerror}") from e
    return image_from_bytes(db, data, ecm_id, path)


def image_from_bytes(db: Database, data: bytes, ecm_id: str | None = None, path: Path | None = None) -> Image:
    where = str(path) if path else "image"
    if ecm_id:
        ecm_id = db.resolve_id(ecm_id)
        lay = db.layout(ecm_id)
        if len(data) not in (lay.size, lay.xsize):
            raise ImageError(
                f"{where}: {len(data)} bytes doesn't fit {ecm_id} "
                f"(.xpr {lay.xsize} bytes, .epr {lay.size} bytes)")
        return Image(ecm_id, lay, bytes(data), path)
    matches = db.ids_for_size(len(data))
    if not matches:
        raise ImageError(f"{where}: no ECM layout has {len(data)} bytes. Check the file, or give the ECM ID.")
    categories = {}
    for m in matches:
        categories.setdefault(m.category, []).append(m.ecm_id)
    if len(categories) > 1:
        groups = "; ".join("/".join(ids) for ids in categories.values())
        raise ImageError(
            f"{where}: {len(data)} bytes fits several layouts ({groups}). "
            "Choose one with the ECM ID option.")
    ids = sorted(next(iter(categories.values())), key=id_order)
    return Image(ids[0], db.layout(ids[0]), bytes(data), path)


def ecm_info(img: Image) -> dict:
    """The fields of EcmDroid's ECM Information screen that live in the EEPROM."""

    def text(name):
        var = img.var(name)
        if var is None or not img.available(var):
            return None
        return format_value(var, img.values(var)[0])

    info = {
        "layout_revision": text("CSR"),
        "country_id": text("Country_ID"),
        "calibration_id": text("Cal_ID"),
        "serial_no": text("KMFG_Serial"),
        "mfg_date": None,
    }
    if info["country_id"] == "255":
        info["country_id"] = "S{}-M{}-V{}".format(
            text("KID_Series") or "?", text("KID_Market") or "?", text("KID_Version") or "?")
    year, day = text("KMFG_Year"), text("KMFG_Day")
    if year is not None and day is not None:
        y = int(year) + 2000
        if y >= 2090:
            y -= 100  # 1990..1999, as in ECM.getMfgDate()
        try:
            date = datetime.date(y, 1, 1) + datetime.timedelta(days=int(day))
            info["mfg_date"] = date.isoformat()
        except (ValueError, OverflowError):
            info["mfg_date"] = None
    return info
