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
"""Compare two EEPROM images by variable name, also across layouts (`calconv diff`)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .analysis import covered_mask, definition_differences
from .db import VarDef
from .image import Image, element_ints

EQUAL, CHANGED, ONLY_A, ONLY_B, MISSING_A, MISSING_B = (
    "equal", "changed", "only in A", "only in B", "not in image A", "not in image B")


@dataclass
class Entry:
    name: str
    status: str
    var_a: VarDef | None
    var_b: VarDef | None
    values_a: list | None = None
    values_b: list | None = None
    changed_cells: list[int] = field(default_factory=list)
    definition: list[str] = field(default_factory=list)  # definition differences, if any
    private: bool = False

    @property
    def var(self) -> VarDef:
        return self.var_a or self.var_b


@dataclass
class ByteSummary:
    """Raw byte differences, for two images of the same layout."""

    pages: int  # differing bytes in pages 1..n
    page0: int | None  # differing bytes in page 0, None if one image lacks it
    uncovered: int  # differing bytes no variable describes
    uncovered_offsets: list[int] = field(default_factory=list)


@dataclass
class Diff:
    a: Image
    b: Image
    entries: list[Entry]
    bytes: ByteSummary | None

    def by_status(self, status: str) -> list[Entry]:
        return [e for e in self.entries if e.status == status]

    @property
    def identical(self) -> bool:
        if any(e.status != EQUAL for e in self.entries):
            return False
        return self.bytes is None or (
            self.bytes.pages == 0 and not self.bytes.page0 and self.bytes.uncovered == 0)


def _same_values(va: list, vb: list) -> list[int]:
    """Indices of differing elements; every index past the shorter list differs."""
    out = []
    for i in range(max(len(va), len(vb))):
        if i >= len(va) or i >= len(vb):
            out.append(i)
            continue
        x, y = va[i], vb[i]
        numbers = isinstance(x, (int, float)) and isinstance(y, (int, float))
        if numbers and (isinstance(x, float) or isinstance(y, float)):
            if not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9):
                out.append(i)
        elif x != y:
            out.append(i)
    return out


def diff_images(a: Image, b: Image, private: tuple[str, ...] = ()) -> Diff:
    same_layout = a.layout.category == b.layout.category
    names = list(a.layout.vars) + [n for n in b.layout.vars if n not in a.layout.vars]
    entries = []
    for name in names:
        va, vb = a.layout.vars.get(name), b.layout.vars.get(name)
        e = Entry(name, EQUAL, va, vb, private=name in private)
        if va is None:
            e.status = ONLY_B
        elif vb is None:
            e.status = ONLY_A
        elif not a.available(va):
            e.status = MISSING_A
        elif not b.available(vb):
            e.status = MISSING_B
        else:
            e.definition = [] if same_layout else definition_differences(va, a.layout, vb, b.layout)
            e.values_a, e.values_b = a.physical(va), b.physical(vb)
            if not e.definition and a.raw(va) == b.raw(vb):
                e.status = EQUAL
            elif not e.definition:
                # Same definition: compare the raw elements, which is exact.
                ia, ib = element_ints(va, a.raw(va)), element_ints(vb, b.raw(vb))
                e.changed_cells = [i for i, (x, y) in enumerate(zip(ia, ib)) if x != y] or [0]
                e.status = CHANGED
            else:
                e.changed_cells = _same_values(e.values_a, e.values_b)
                e.status = CHANGED
        if e.values_a is None and va is not None and a.available(va):
            e.values_a = a.physical(va)
        if e.values_b is None and vb is not None and b.available(vb):
            e.values_b = b.physical(vb)
        entries.append(e)

    summary = None
    if same_layout:
        lay = a.layout
        mask = covered_mask(lay)
        pages = page0 = uncovered = 0
        offsets = []
        for i in range(min(lay.size, len(a.data), len(b.data))):
            if a.data[i] != b.data[i]:
                pages += 1
                if not mask[i]:
                    uncovered += 1
                    offsets.append(i)
        if a.has_page0 and b.has_page0:
            for i in range(lay.size, lay.xsize):
                if a.data[i] != b.data[i]:
                    page0 += 1
                    if not mask[i]:
                        uncovered += 1
                        offsets.append(i)
        else:
            page0 = None
        summary = ByteSummary(pages, page0, uncovered, offsets)
    return Diff(a, b, entries, summary)
