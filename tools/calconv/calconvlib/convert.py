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
"""Carry a calibration from a source image onto a target image of another
layout (`calconv convert`, phase 3: exact matches only).

The result starts as a copy of the target. Only variables with an identical
definition in both layouts are copied, as raw bytes. Everything else keeps
the target's value. See docs/calibration-converter.md, "Conversion rules".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import Plan, make_plan, undescribed_bits
from .db import Database, VarDef
from .image import Image, image_from_bytes
from .rules import CommonRules

COPIED = "copied"  # the result has the source's value, which differs from the target's
EQUAL = "equal"  # copyable, and source and target already had the same value
KEPT = "kept"  # shared, but the target's value is kept; needs review
EXCLUDED = "excluded"  # never copied by rule (page 0, identification, per unit, model guard)
LOST = "lost"  # only in the source layout
TARGET_ONLY = "target only"  # only in the target layout; its value is kept


class ConversionError(Exception):
    """The images can't be converted (different families, model guard, ...)."""


@dataclass
class Action:
    name: str
    action: str
    reason: str = ""
    var_s: VarDef | None = None
    var_t: VarDef | None = None
    source: list | None = None  # physical values in the source image
    before: list | None = None  # physical values in the target image
    after: list | None = None  # physical values in the result
    bits_kept: list[int] = field(default_factory=list)  # undescribed bits that differ and were kept

    @property
    def var(self) -> VarDef:
        return self.var_t or self.var_s


@dataclass
class Conversion:
    plan: Plan
    source: Image
    target: Image
    result: Image
    actions: dict[str, Action]
    model_mismatch: dict[str, tuple[str, str]]  # name -> (source raw hex, target raw hex)
    changed_pages: dict[int, int]  # page number -> bytes that differ from the target
    problems: list[str]  # verification failures; empty means the result checks out

    def by_action(self, action: str) -> list[Action]:
        return [a for a in self.actions.values() if a.action == action]


class _Groups:
    """Union-find over variable names."""

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str):
        self.parent[self.find(a)] = self.find(b)

    def members(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for x in self.parent:
            out.setdefault(self.find(x), []).append(x)
        return out


def _described_mask(db: Database, var: VarDef) -> int:
    mask = 0xFF
    for bit in undescribed_bits(db, var):
        mask &= ~(1 << (bit - 1))
    return mask


def convert(db: Database, source: Image, target: Image, rules: CommonRules,
            allow_model_mismatch: bool = False) -> Conversion:
    if source.layout.family != target.layout.family:
        raise ConversionError(
            f"{source.ecm_id} is {source.layout.family} and {target.ecm_id} is {target.layout.family}; "
            "converting between families isn't supported")
    plan = make_plan(db, source.ecm_id, target.ecm_id, rules)
    src, dst = source.layout, target.layout

    # Rule 5: model guard. Different engine/harness variables mean the
    # source is probably from another model.
    mismatch = {}
    for name in rules.model_guard:
        vs, vt = src.vars.get(name), dst.vars.get(name)
        if vs and vt and source.available(vs) and target.available(vt) and source.raw(vs) != target.raw(vt):
            mismatch[name] = (source.raw(vs).hex(), target.raw(vt).hex())
    if mismatch and not allow_model_mismatch:
        details = ", ".join(f"{n}: source {s}, target {t}" for n, (s, t) in mismatch.items())
        raise ConversionError(
            f"model guard: {details}. The source is probably from another model. "
            "Use --allow-model-mismatch only if you know both are the same model.")

    actions: dict[str, Action] = {}

    def add(name, action, reason="", vs=None, vt=None):
        actions[name] = Action(name, action, reason, vs, vt,
                               source=source.physical(vs) if vs is not None and source.available(vs) else None,
                               before=target.physical(vt) if vt is not None and target.available(vt) else None)

    candidates = []
    for name in plan.shared:
        vs, vt = src.vars[name], dst.vars[name]
        if name in plan.excluded:
            add(name, EXCLUDED, plan.excluded[name], vs, vt)
        elif name in rules.model_guard:
            add(name, EXCLUDED, "model guard", vs, vt)
        elif name in plan.different:
            add(name, KEPT, "different definition: " + "; ".join(plan.different[name]), vs, vt)
        elif name in plan.semantic:
            add(name, KEPT, "the description says the meaning depends on the firmware", vs, vt)
        elif not source.available(vs) or not target.available(vt):
            add(name, KEPT, "not in both images (no page 0)", vs, vt)
        else:
            candidates.append(name)
    for name in plan.src_only:
        if name in rules.identification:
            add(name, EXCLUDED, "identification", src.vars[name], None)
        else:
            add(name, LOST, f"{target.ecm_id} has no such variable", src.vars[name], None)
    for name in plan.dst_only:
        add(name, TARGET_ONLY, "", None, dst.vars[name])

    # Rules 6 and 8: variables that share target bytes, and maps with their
    # axes, are copied together or not at all.
    groups = _Groups()
    for name in dst.vars:
        groups.find(name)
    spans = sorted((dst.position(v), dst.position(v) + v.size, v.name) for v in dst.vars.values())
    for i, (s1, e1, n1) in enumerate(spans):
        for s2, e2, n2 in spans[i + 1:]:
            if s2 >= e1:
                break
            groups.union(n1, n2)
    for v in dst.vars.values():
        if v.type == "Map":
            for ax in dst.axis_refs(v):
                if ax:
                    groups.union(v.name, ax)
    candidate_set = set(candidates)
    blocked: dict[str, str] = {}
    for members in groups.members().values():
        if len(members) == 1:
            continue
        outside = [m for m in members if m not in candidate_set]
        if outside:
            for m in members:
                if m in candidate_set:
                    blocked[m] = f"belongs together with {', '.join(sorted(outside))}, which isn't copied"
            continue
        # Overlapping members must overlap the same way in the source, and
        # bitfields can't be partly copied inside a group.
        for a in members:
            for b in members:
                if a < b and (src.position(src.vars[a]) - src.position(src.vars[b])
                              != dst.position(dst.vars[a]) - dst.position(dst.vars[b])):
                    pa, pb = dst.position(dst.vars[a]), dst.position(dst.vars[b])
                    if pa < pb + dst.vars[b].size and pb < pa + dst.vars[a].size:
                        for m in members:
                            blocked[m] = f"{a} and {b} overlap differently in the two layouts"
        for m in members:
            v = dst.vars[m]
            if v.type == "Bits" and undescribed_bits(db, v) and m not in blocked:
                for n in members:
                    blocked[n] = f"bitfield {m} shares bytes with other variables"
    for name in candidates:
        if name in blocked:
            add(name, KEPT, blocked[name], src.vars[name], dst.vars[name])

    # Copy.
    data = bytearray(target.data)
    written = bytearray(len(data))
    for name in candidates:
        if name in blocked:
            continue
        vs, vt = src.vars[name], dst.vars[name]
        s_raw, t_start = source.raw(vs), target.start(vt)
        kept_bits = []
        if vt.type == "Bits":
            mask = _described_mask(db, vt)
            for i, b in enumerate(s_raw):
                old = data[t_start + i]
                data[t_start + i] = (old & ~mask & 0xFF) | (b & mask)
                if (old ^ b) & ~mask & 0xFF:
                    kept_bits += [bit + 1 for bit in range(8) if ((old ^ b) & ~mask) >> bit & 1]
                written[t_start + i] = 1
        else:
            data[t_start:t_start + vt.size] = s_raw
            for i in range(vt.size):
                written[t_start + i] = 1
        same = bytes(data[t_start:t_start + vt.size]) == target.raw(vt)
        add(name, EQUAL if same else COPIED, "", vs, vt)
        actions[name].bits_kept = kept_bits

    result = image_from_bytes(db, bytes(data), target.ecm_id)
    for a in actions.values():
        if a.var_t is not None and result.available(a.var_t):
            a.after = result.physical(a.var_t)

    # Verify: copied variables hold the source's bytes (described bits for
    # bitfields), and every other byte is the target's.
    problems = []
    if len(result.data) != len(target.data):
        problems.append(f"result has {len(result.data)} bytes, target {len(target.data)}")
    for a in actions.values():
        if a.action not in (COPIED, EQUAL):
            continue
        r, s = result.raw(a.var_t), source.raw(a.var_s)
        if a.var_t.type == "Bits":
            mask = _described_mask(db, a.var_t)
            if any((x ^ y) & mask for x, y in zip(r, s)):
                problems.append(f"{a.name}: described bits differ from the source")
        elif r != s:
            problems.append(f"{a.name}: bytes differ from the source")
    for i, (x, y) in enumerate(zip(result.data, target.data)):
        if x != y and not written[i]:
            problems.append(f"byte {i} changed although no copied variable covers it")

    changed_pages = {}
    for page in dst.pages:
        if page.start + page.size > len(data):
            continue
        n = sum(1 for i in range(page.start, page.start + page.size) if result.data[i] != target.data[i])
        if n:
            changed_pages[page.nr] = n
    return Conversion(plan, source, target, result, actions, mismatch, changed_pages, problems)
