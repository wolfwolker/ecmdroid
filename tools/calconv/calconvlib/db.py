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
"""Read access to EcmDroid's bundled ECM definition database.

The database comes from the ecmspy.com project. Its structure is described in
docs/database.md. This module only reads the EEPROM side (tables eeprom,
pages, eeoffsets, names, bits).
"""

from __future__ import annotations

import gzip
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "app" / "src" / "main" / "assets" / "ecmdroid.db.gz"


class DatabaseError(Exception):
    """The database can't be read, or an ECM ID is unknown."""


def id_order(ecm_id: str) -> tuple[bool, str]:
    """Sort key: stock IDs (BUExx) before race IDs (B2Rxx, B3Rxx)."""
    return (not ecm_id.startswith("BUE"), ecm_id)


def _float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Page:
    nr: int
    size: int
    start: int  # offset in the in-memory image; page 0 is appended at the end


@dataclass(frozen=True)
class VarDef:
    """One EEPROM variable of one layout (a row of eeoffsets plus its names row)."""

    name: str
    type: str  # as in the database: Value, Bits, Array, Axis, Table, Map, String
    size: int
    offset: int  # buffer offset; negative = page 0, counted from the end
    elemsize: int | None
    elements: int | None
    cols: int | None
    rows: int | None
    skip: int | None
    scale: float | None
    translate: float | None
    axisscale: float | None
    axistranslate: float | None
    xaxis: str | None
    yaxis: str | None
    label: str | None = None
    remark: str | None = None
    description: str | None = None
    units: str | None = None
    fmt: str | None = None
    axisunits: str | None = None
    axisformat: str | None = None

    @property
    def width(self) -> int:
        """Bytes per element, as Variable.setWidth() computes it."""
        return max(self.elemsize or 0, 1)

    @property
    def count(self) -> int:
        """Number of elements, as Variable.init() computes it (size / width)."""
        return self.size // self.width

    @property
    def in_page0(self) -> bool:
        return self.offset < 0


@dataclass
class Layout:
    """An EEPROM layout (one database category), shared by one or more ECM IDs."""

    category: int
    ids: list[str]
    family: str  # DDFI, DDFI-2, DDFI-3
    size: int  # pages 1..n (.epr size)
    xsize: int  # pages 1..n plus page 0 (.xpr size)
    pages: list[Page]
    vars: dict[str, VarDef]  # ordered by position in the image
    remarks: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def page0_size(self) -> int:
        return self.xsize - self.size

    def position(self, var: VarDef) -> int:
        """Start of a variable in an .xpr image (page 0 at the end)."""
        return var.offset if var.offset >= 0 else self.xsize + var.offset

    def axis_refs(self, var: VarDef) -> tuple[str | None, str | None]:
        """The xaxis/yaxis entries that name a variable of this layout.

        Maps reference separate Axis variables. Tables use the same columns
        for plain labels such as "Engine Temperature", which are ignored here.
        """
        return tuple(ax if ax and ax in self.vars else None for ax in (var.xaxis, var.yaxis))


@dataclass(frozen=True)
class SizeMatch:
    ecm_id: str
    category: int
    kind: str  # ".xpr" (with page 0) or ".epr" (without)


class Database:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        try:
            raw = self.path.read_bytes()
        except OSError as e:
            raise DatabaseError(f"can't read database {self.path}: {e.strerror}") from e
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        self._con = sqlite3.connect(":memory:")
        self._con.row_factory = sqlite3.Row
        try:
            self._con.deserialize(raw)
            ecms = self._con.execute(
                "SELECT name, category, type, size, xsize, remark FROM eeprom ORDER BY name").fetchall()
        except sqlite3.DatabaseError as e:
            raise DatabaseError(f"{self.path} isn't an ECM definition database: {e}") from e
        self._ecms = {row["name"]: row for row in ecms}
        self._names = {row["varname"]: row for row in self._con.execute(
            "SELECT varname, name, remark, description, units, format, axisunits, axisformat FROM names")}
        self._bits = {row["varname"]: [(row[f"bit{i}"] or "").strip() or None for i in range(1, 9)]
                      for row in self._con.execute("SELECT * FROM bits")}
        self._layouts: dict[int, Layout] = {}

    def ids(self) -> list[str]:
        return list(self._ecms)

    def resolve_id(self, text: str) -> str:
        """Accept an ECM ID or a version string; its first 5 characters are the ID."""
        ecm_id = (text or "").strip().upper()[:5]
        if ecm_id not in self._ecms:
            raise DatabaseError(f"unknown ECM ID {text!r}. Known IDs: {', '.join(self._ecms)}")
        return ecm_id

    def layout(self, ecm_id: str) -> Layout:
        row = self._ecms[self.resolve_id(ecm_id)]
        category = row["category"]
        if category not in self._layouts:
            self._layouts[category] = self._load_layout(category)
        return self._layouts[category]

    def layouts(self) -> list[Layout]:
        seen = []
        for ecm_id in self._ecms:
            lay = self.layout(ecm_id)
            if lay not in seen:
                seen.append(lay)
        return seen

    def ids_for_size(self, length: int) -> list[SizeMatch]:
        """All ECM IDs whose .xpr or .epr size is `length` (like EEPROM.size2id())."""
        out = []
        for name, row in self._ecms.items():
            if length == row["xsize"]:
                out.append(SizeMatch(name, row["category"], ".xpr"))
            elif length == row["size"]:
                out.append(SizeMatch(name, row["category"], ".epr"))
        return out

    def bit_labels(self, varname: str) -> list[str | None]:
        return self._bits.get(varname, [None] * 8)

    def _load_layout(self, category: int) -> Layout:
        rows = [r for r in self._ecms.values() if r["category"] == category]
        first = rows[0]
        lay = Layout(
            category=category,
            ids=sorted((r["name"] for r in rows), key=id_order),
            family=first["type"],
            size=first["size"],
            xsize=first["xsize"],
            pages=[],
            vars={},
            remarks={r["name"]: r["remark"] for r in rows},
        )
        page_rows = self._con.execute(
            "SELECT page, size FROM pages WHERE category = ? ORDER BY page", (category,)).fetchall()
        start = 0
        for r in page_rows:
            if r["page"] != 0:
                lay.pages.append(Page(r["page"], r["size"], start))
                start += r["size"]
        for r in page_rows:
            if r["page"] == 0:
                lay.pages.append(Page(0, r["size"], start))
                start += r["size"]
        data_pages = sum(p.size for p in lay.pages if p.nr != 0)
        if data_pages != lay.size:
            lay.warnings.append(f"pages 1..n add up to {data_pages} bytes, eeprom.size is {lay.size}")
        if start != lay.xsize:
            lay.warnings.append(f"all pages add up to {start} bytes, eeprom.xsize is {lay.xsize}")

        defs = {}
        for r in self._con.execute("SELECT * FROM eeoffsets WHERE category = ? ORDER BY uniqueid", (category,)):
            name = r["varname"]
            if name in defs:
                first = defs[name]
                if (first.offset, first.size, first.type) == (r["offset"], r["size"], r["type"]):
                    lay.warnings.append(f"{name} is listed twice")
                else:
                    lay.warnings.append(
                        f"{name} is defined twice (offset {first.offset}, {first.size} bytes and offset "
                        f"{r['offset']}, {r['size']} bytes); the first one is used")
                continue
            n = self._names.get(name)
            defs[name] = (VarDef(
                name=r["varname"],
                type=r["type"],
                size=r["size"],
                offset=r["offset"],
                elemsize=_int(r["elemsize"]),
                elements=_int(r["elements"]),
                cols=_int(r["cols"]),
                rows=_int(r["rows"]),
                skip=_int(r["skip"]),
                scale=_float(r["scale"]),
                translate=_float(r["translate"]),
                axisscale=_float(r["axisscale"]),
                axistranslate=_float(r["axistranslate"]),
                xaxis=r["xaxis"] or None,
                yaxis=r["yaxis"] or None,
                label=(n["name"] or None) if n else None,
                remark=(n["remark"] or None) if n else None,
                description=(n["description"] or None) if n else None,
                units=(n["units"] or None) if n else None,
                fmt=(n["format"] or None) if n else None,
                axisunits=(n["axisunits"] or None) if n else None,
                axisformat=(n["axisformat"] or None) if n else None,
            ))
        ordered = sorted(defs.values(), key=lambda v: (lay.position(v), v.name))
        lay.vars = {v.name: v for v in ordered}
        return lay
