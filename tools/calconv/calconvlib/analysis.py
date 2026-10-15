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
"""Layout analysis without images: what a conversion between two layouts
could copy, what it would lose, and what needs a decision (`calconv plan`)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .db import Database, Layout, VarDef
from .rules import CommonRules

# A description that names ECM IDs, or the family of the layouts being
# compared, hints that the meaning depends on the firmware (e.g.
# Tab_Idle_Spark: "early DDFI-3 (BUEOD ... BUEZD)" vs "later DDFI-3").
_ECM_ID_HINT = r"\bBUE[A-Z0-9]{2}\b|\bB[23]R[A-Z0-9]{2}\b"


def _firmware_hint(families: set[str]) -> re.Pattern:
    parts = [_ECM_ID_HINT] + [re.escape(f) + r"(?![-\d])" for f in sorted(families)]
    return re.compile("|".join(parts), re.I)


_UNDESCRIBED_BIT = {"", "unknown", "(unknown)", "reserved", "(reserved)"}
CANDIDATE_THRESHOLD = 1.0


def _same_number(a: float | None, b: float | None, default: float) -> bool:
    """Compare scale-like values. The database stores them as text with
    different precision (1.000000 vs 1.00000000, 0.01333 vs 0.013333), so
    values within 0.1% count as equal."""
    a = default if not a else a
    b = default if not b else b
    return math.isclose(a, b, rel_tol=1e-3, abs_tol=1e-9)


def definition_differences(a: VarDef, la: Layout, b: VarDef, lb: Layout) -> list[str]:
    """Why two definitions of the same name can't be copied byte for byte.

    Only attributes that change how the bytes are read count, the same ones
    the app uses: type, size and element width; rows/columns of tables and
    maps; scale and translate of values (and of the axis half of tables);
    and the axis variables of maps. The database's `elements` column is
    ignored, like in the app (database_warnings() reports contradictions).
    """
    out = []
    attrs = ["type", "size", "width"]
    if a.type in ("Table", "Map") or b.type in ("Table", "Map"):
        attrs += ["cols", "rows"]
    if a.type == "Map" or b.type == "Map":
        attrs.append("skip")
    for attr in attrs:
        va, vb = getattr(a, attr), getattr(b, attr)
        if (va or 0) != (vb or 0):
            out.append(f"{attr} {va} → {vb}")
    numbers = []
    if a.type not in ("Bits", "String") or b.type not in ("Bits", "String"):
        numbers += [("scale", 1.0), ("translate", 0.0)]
    if a.type == "Table" or b.type == "Table":
        numbers += [("axisscale", 1.0), ("axistranslate", 0.0)]
    for attr, default in numbers:
        va, vb = getattr(a, attr), getattr(b, attr)
        if not _same_number(va, vb, default):
            out.append(f"{attr} {va} → {vb}")
    if (a.type == "Map" or b.type == "Map") and la.axis_refs(a) != lb.axis_refs(b):
        out.append(f"axes {la.axis_refs(a)} → {lb.axis_refs(b)}")
    return out


def database_warnings(lay: Layout) -> list[str]:
    """Definitions that contradict themselves or overlap."""
    out = list(lay.warnings)
    spans = []
    for v in lay.vars.values():
        if v.size % v.width:
            out.append(f"{v.name}: size {v.size} isn't a multiple of elemsize {v.width}")
        skip = (v.skip or 0) if v.type == "Map" else 0
        if v.type in ("Table", "Map") and v.cols and v.rows:
            if (v.cols + skip) * v.rows != v.count:
                padding = f" plus {skip} skipped per row" if skip else ""
                out.append(f"{v.name}: {v.cols}×{v.rows} cells{padding} don't match {v.count} elements")
            expected_elements = v.cols * v.rows
        else:
            expected_elements = v.count
        if v.elements and v.elements != expected_elements:
            out.append(f"{v.name}: elements column says {v.elements}, but {v.size} bytes hold {v.count} "
                       "(the app ignores the column)")
        pos = lay.position(v)
        if pos < 0 or pos + v.size > lay.xsize:
            out.append(f"{v.name}: bytes {pos}..{pos + v.size - 1} are outside the {lay.xsize}-byte image")
        spans.append((pos, pos + v.size, v.name))
    spans.sort()
    for (s1, e1, n1), (s2, e2, n2) in zip(spans, spans[1:]):
        if s2 < e1:
            out.append(f"{n1} and {n2} describe the same {min(e1, e2) - s2} byte(s) at {s2} "
                       "(often intended, e.g. a table and its single values)")
    return out


def coverage(lay: Layout) -> tuple[int, int]:
    """Bytes described by at least one variable, and the image size."""
    covered = bytearray(lay.xsize)
    for v in lay.vars.values():
        pos = lay.position(v)
        for i in range(max(pos, 0), min(pos + v.size, lay.xsize)):
            covered[i] = 1
    return sum(covered), lay.xsize


def covered_mask(lay: Layout) -> bytearray:
    mask = bytearray(lay.xsize)
    for v in lay.vars.values():
        pos = lay.position(v)
        for i in range(max(pos, 0), min(pos + v.size, lay.xsize)):
            mask[i] = 1
    return mask


def undescribed_bits(db: Database, var: VarDef) -> list[int]:
    """Bit numbers (1..8) without a description in the bits table."""
    labels = db.bit_labels(var.name)
    return [i + 1 for i, label in enumerate(labels) if (label or "").strip().lower() in _UNDESCRIBED_BIT]


def _normalize(name: str) -> str:
    n = re.sub(r"_(LD|2)$", "", name, flags=re.I).lower()
    n = n.replace("load", "tp")
    return n.replace("_", "")


def _previous_shared(order: list[str], index: int, other: Layout) -> str | None:
    for name in reversed(order[:index]):
        if name in other.vars:
            return name
    return None


@dataclass
class Candidate:
    target: str
    score: float
    signals: list[str]


def rename_candidates(src: Layout, dst: Layout, src_only: list[str], dst_only: list[str]) -> dict[str, list[Candidate]]:
    """Score possible renames. Never applied automatically: a person decides."""
    src_order, dst_order = list(src.vars), list(dst.vars)
    out = {}
    for s in src_only:
        a = src.vars[s]
        prev_a = _previous_shared(src_order, src_order.index(s), dst)
        found = []
        for t in dst_only:
            b = dst.vars[t]
            score, signals = 0.0, []
            if a.label and b.label and a.label.strip().lower() == b.label.strip().lower():
                score += 1.0
                signals.append("same label")
            if _normalize(s) == _normalize(t):
                score += 1.0
                signals.append("same normalized name")
            else:
                score += SequenceMatcher(None, s.lower(), t.lower()).ratio()
            if (a.type, a.size) == (b.type, b.size):
                score += 0.3
                signals.append("same type and size")
            prev_b = _previous_shared(dst_order, dst_order.index(t), src)
            if prev_a is not None and prev_a == prev_b:
                score += 0.5
                signals.append(f"same position (after {prev_a})")
            if score >= CANDIDATE_THRESHOLD:
                found.append(Candidate(t, round(score, 2), signals))
        if found:
            found.sort(key=lambda c: (-c.score, c.target))
            out[s] = found[:3]
    return out


@dataclass
class Plan:
    src_id: str
    dst_id: str
    src: Layout
    dst: Layout
    shared: list[str] = field(default_factory=list)
    identical: list[str] = field(default_factory=list)
    same_offset: int = 0  # shared names at the same offset in both layouts
    different: dict[str, list[str]] = field(default_factory=dict)
    src_only: list[str] = field(default_factory=list)
    dst_only: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)  # shared name -> reason
    copyable: list[str] = field(default_factory=list)
    bitfields: list[str] = field(default_factory=list)  # copyable Bits variables
    bitfields_undescribed: dict[str, list[int]] = field(default_factory=dict)
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    semantic: dict[str, str] = field(default_factory=dict)  # name -> description text
    model_guard: dict[str, str] = field(default_factory=dict)  # name -> status
    warnings: dict[str, list[str]] = field(default_factory=dict)  # ECM ID -> database warnings
    coverage: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def same_family(self) -> bool:
        return self.src.family == self.dst.family

    @property
    def same_layout(self) -> bool:
        return self.src.category == self.dst.category


def make_plan(db: Database, src_id: str, dst_id: str, rules: CommonRules) -> Plan:
    src_id, dst_id = db.resolve_id(src_id), db.resolve_id(dst_id)
    src, dst = db.layout(src_id), db.layout(dst_id)
    p = Plan(src_id, dst_id, src, dst)
    hint = _firmware_hint({src.family, dst.family})

    for name, a in src.vars.items():
        b = dst.vars.get(name)
        if b is None:
            p.src_only.append(name)
            continue
        p.shared.append(name)
        if a.offset == b.offset:
            p.same_offset += 1
        diffs = definition_differences(a, src, b, dst)
        if diffs:
            p.different[name] = diffs
        else:
            p.identical.append(name)
        if rules.exclude_page0 and (a.in_page0 or b.in_page0):
            p.excluded[name] = "page 0"
        elif name in rules.identification:
            p.excluded[name] = "identification"
        text = " ".join(t for t in (a.label, a.remark, a.description) if t)
        if hint.search(text):
            p.semantic[name] = re.sub(r"\s+", " ", text).strip()
    p.dst_only = [n for n in dst.vars if n not in src.vars]

    p.copyable = [n for n in p.identical if n not in p.excluded]
    for name in p.copyable:
        var = src.vars[name]
        if var.type == "Bits":
            p.bitfields.append(name)
            bits = sorted(set(undescribed_bits(db, var)))
            if bits:
                p.bitfields_undescribed[name] = bits

    p.candidates = rename_candidates(src, dst, p.src_only, p.dst_only)

    for name in rules.model_guard:
        if name not in src.vars and name not in dst.vars:
            continue
        if name not in src.vars or name not in dst.vars:
            p.model_guard[name] = "only in " + (p.src_id if name in src.vars else p.dst_id)
        elif name in p.different:
            p.model_guard[name] = "different definition"
        else:
            p.model_guard[name] = "compare values before converting"

    for ecm_id, lay in ((src_id, src), (dst_id, dst)):
        if ecm_id not in p.warnings:
            p.warnings[ecm_id] = database_warnings(lay)
            p.coverage[ecm_id] = coverage(lay)
    return p
