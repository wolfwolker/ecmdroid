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
layout (`calconv convert`).

The result starts as a copy of the target. Variables with an identical
definition in both layouts are copied as raw bytes. A pair rule file can add
aliases (renamed variables, also per bit), named transforms (copy_elements,
resample_pairs), reviewed copies of flagged variables, and exclusions.
Everything else keeps the target's value. See docs/calibration-converter.md,
"Conversion rules" and "Rule files".
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import Plan, _same_number, definition_differences, make_plan, undescribed_bits
from .db import Database, Layout, VarDef
from .image import Image, element_ints, element_scale, encode_element, image_from_bytes, pack_ints
from .rules import ALIAS, COPY, COPY_ELEMENTS, EXCLUDE, RESAMPLE_PAIRS, TRANSFORM, CommonRules, PairRules, Rule, RuleError

COPIED = "copied"  # the result has the source's value, which differs from the target's
EQUAL = "equal"  # copyable, and source and target already had the same value
KEPT = "kept"  # shared or ruled, but the target's value is kept; needs review
EXCLUDED = "excluded"  # never copied by rule (page 0, identification, per unit, model guard, rule file)
LOST = "lost"  # only in the source layout
TARGET_ONLY = "target only"  # only in the target layout; its value is kept

# How a variable was written.
RAW = "raw"  # source bytes (described bits for bitfields)
SCALED = "scaled"  # decoded, converted to the target's scale and rounded
ELEMENTS = "elements"  # copy_elements
RESAMPLED = "resampled"  # resample_pairs
BIT = "bit"  # one bit, from a per-bit alias

_SCALE_ATTRS = ("scale ", "translate ", "axisscale ", "axistranslate ")


class ConversionError(Exception):
    """The images can't be converted (different families, model guard, ...)."""


@dataclass
class Action:
    name: str  # target name; "Name[bit]" for per-bit aliases
    action: str
    reason: str = ""
    var_s: VarDef | None = None
    var_t: VarDef | None = None
    source: list | None = None  # physical values in the source image
    before: list | None = None  # physical values in the target image
    after: list | None = None  # physical values in the result
    bits_kept: list[int] = field(default_factory=list)  # undescribed bits that differ and were kept
    rule: Rule | None = None  # the rule-file entry that decided this action
    how: str = ""  # RAW, SCALED, ELEMENTS, RESAMPLED, BIT
    bit: tuple[int, int] | None = None  # (source bit, target bit) for BIT
    expected: list | None = None  # resample_pairs: the physical values that were encoded

    @property
    def var(self) -> VarDef:
        return self.var_t or self.var_s

    @property
    def source_name(self) -> str:
        return self.var_s.name if self.var_s else ""


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
    pair: PairRules | None = None
    allow_proposed: bool = False
    applied: list[Rule] = field(default_factory=list)
    pending: list[Rule] = field(default_factory=list)  # proposed, not applied
    skipped: list[tuple[Rule, str]] = field(default_factory=list)  # active, but overruled

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


def protected_reason(name: str, lay: Layout, plan: Plan, rules: CommonRules) -> str | None:
    """Why a variable of either layout is never copied, or None."""
    var = lay.vars[name]
    if rules.exclude_page0 and var.in_page0:
        return "page 0"
    if name in rules.identification:
        return "identification"
    if name in rules.per_unit:
        return "per unit"
    if name in rules.model_guard:
        return "model guard"
    return plan.excluded.get(name)


def _scale_compatible(a: VarDef, b: VarDef) -> bool:
    return (_same_number(a.scale, b.scale, 1.0) and _same_number(a.translate, b.translate, 0.0)
            and (a.type != "Table" or (_same_number(a.axisscale, b.axisscale, 1.0)
                                       and _same_number(a.axistranslate, b.axistranslate, 0.0))))


def check_rules(db: Database, pair: PairRules, plan: Plan, rules: CommonRules):
    """Static checks of every entry, reviewed or not, against both layouts."""
    src, dst = plan.src, plan.dst
    if pair.src_id not in src.ids or pair.dst_id not in dst.ids:
        raise RuleError(f"{pair.path}: the rules are for {pair.src_id} → {pair.dst_id}, "
                        f"not {plan.src_id} → {plan.dst_id}")
    for r in pair.rules:
        def fail(msg):
            raise RuleError(f"{r.where}: {msg}")

        if r.kind == EXCLUDE:
            if r.source.name not in src.vars and r.source.name not in dst.vars:
                fail(f"{r.source.name} is in neither {plan.src_id} nor {plan.dst_id}")
            continue
        if r.source.name not in src.vars:
            fail(f"{r.source.name} isn't a {plan.src_id} variable")
        for t in r.targets:
            if t.name not in dst.vars:
                fail(f"{t.name} isn't a {plan.dst_id} variable")
            why = protected_reason(t.name, dst, plan, rules)
            if why:
                fail(f"{t.name} is never written ({why})")
        if r.kind == COPY:
            if r.source.name not in plan.shared:
                fail(f"{r.source.name} isn't in both layouts; use [[alias]]")
            if r.source.name in plan.different:
                fail(f"{r.source.name} has a different definition ({'; '.join(plan.different[r.source.name])}); "
                     "copy needs an identical one, use a transform")
            continue
        vs = src.vars[r.source.name]
        if r.kind == ALIAS and r.source.bit is not None:
            for ref, lay in [(r.source, src)] + [(t, dst) for t in r.targets]:
                if lay.vars[ref.name].type != "Bits":
                    fail(f"{ref.name} isn't a bitfield")
            continue
        if r.kind == TRANSFORM:
            vt = dst.vars[r.targets[0].name]
            if r.transform == COPY_ELEMENTS:
                if vs.type != vt.type or vs.width != vt.width or not _scale_compatible(vs, vt):
                    fail(f"{COPY_ELEMENTS} needs the same type, element width and scale "
                         f"({vs.type}/{vs.width}/{vs.scale} vs {vt.type}/{vt.width}/{vt.scale})")
                if vs.type in ("Bits", "String"):
                    fail(f"{COPY_ELEMENTS} doesn't work on {vs.type} variables")
                if r.source_start + r.count > vs.count or r.target_start + r.count > vt.count:
                    fail(f"{r.count} elements from {r.source_start + 1} (source has {vs.count}) "
                         f"to {r.target_start + 1} (target has {vt.count}) don't fit")
                if vs.type == "Table" and (r.source_start % 2 or r.target_start % 2 or r.count % 2):
                    fail("tables hold axis/value pairs: starts and count must be even")
            elif vs.type != "Table" or vt.type != "Table":
                fail(f"{RESAMPLE_PAIRS} needs two self-contained tables (axis/value pairs)")


def _interpolate(points: list[tuple[float, float]], x: float) -> float:
    """Linear interpolation, clamped to the first and last point."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _resample(vs: VarDef, src_vals: list, vt: VarDef, dst_vals: list) -> tuple[list | None, str]:
    """The target table's values, interpolated from the source table onto the
    target's own axis. Returns (physical values, "") or (None, reason)."""
    points = [(src_vals[i], src_vals[i + 1]) for i in range(0, len(src_vals) - 1, 2)]
    if any(b[0] < a[0] for a, b in zip(points, points[1:])):
        return None, "the source axis isn't in ascending order"
    out = list(dst_vals)
    for i in range(0, len(out) - 1, 2):
        out[i + 1] = _interpolate(points, dst_vals[i])
    return out, ""


def convert(db: Database, source: Image, target: Image, rules: CommonRules, pair: PairRules | None = None,
            allow_model_mismatch: bool = False, allow_proposed: bool = False) -> Conversion:
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

    # Pair rules: check them all, then keep the active ones. Exclusions win.
    applied, pending, skipped = [], [], []
    rule_excluded: dict[str, Rule] = {}
    copy_ok: dict[str, Rule] = {}
    handled: dict[str, Rule] = {}  # target name -> alias or transform
    bit_rules: list[tuple[Rule, int]] = []  # (rule, index of the target)
    if pair is not None:
        check_rules(db, pair, plan, rules)
        active = []
        for r in pair.rules:
            (active if r.reviewed or allow_proposed else pending).append(r)
        for r in active:
            if r.kind == EXCLUDE:
                rule_excluded[r.source.name] = r
                applied.append(r)
        taken_bits: dict[tuple[str, int], Rule] = {}
        for r in active:
            if r.kind == EXCLUDE:
                continue
            excluded = [t.name for t in r.targets if t.name in rule_excluded]
            if excluded or r.source.name in rule_excluded:
                skipped.append((r, f"excluded by {rule_excluded[(excluded or [r.source.name])[0]].where}"))
                continue
            for i, t in enumerate(r.targets):
                if t.bit is not None:
                    other = taken_bits.get((t.name, t.bit))
                    if other:
                        raise RuleError(f"{r.where}: {t} is also written by {other.where}")
                    taken_bits[(t.name, t.bit)] = r
                    bit_rules.append((r, i))
                    continue
                other = handled.get(t.name) or copy_ok.get(t.name)
                if other:
                    raise RuleError(f"{r.where}: {t.name} is also written by {other.where}")
                (copy_ok if r.kind == COPY else handled)[t.name] = r
            applied.append(r)
    # Sources of whole-variable aliases aren't lost; a per-bit alias carries one bit only.
    alias_sources = {r.source.name for r in handled.values() if r.source.name not in dst.vars}

    actions: dict[str, Action] = {}

    def add(name, action, reason="", vs=None, vt=None, rule=None):
        actions[name] = Action(name, action, reason, vs, vt,
                               source=source.physical(vs) if vs is not None and source.available(vs) else None,
                               before=target.physical(vt) if vt is not None and target.available(vt) else None,
                               rule=rule)
        return actions[name]

    candidates, ruled = [], []
    for name in plan.shared:
        vs, vt = src.vars[name], dst.vars[name]
        if name in plan.excluded:
            add(name, EXCLUDED, plan.excluded[name], vs, vt)
        elif name in rules.model_guard:
            add(name, EXCLUDED, "model guard", vs, vt)
        elif name in rule_excluded:
            add(name, EXCLUDED, "rule: " + rule_excluded[name].why, vs, vt, rule_excluded[name])
        elif name in handled:
            ruled.append(name)
        elif not source.available(vs) or not target.available(vt):
            add(name, KEPT, "not in both images (no page 0)", vs, vt)
        elif name in copy_ok:
            candidates.append(name)
        elif name in plan.different:
            add(name, KEPT, "different definition: " + "; ".join(plan.different[name]), vs, vt)
        elif name in plan.semantic:
            add(name, KEPT, "the description says the meaning depends on the firmware", vs, vt)
        else:
            candidates.append(name)
    for name in plan.src_only:
        if name in rules.identification:
            add(name, EXCLUDED, "identification", src.vars[name], None)
        elif name in rule_excluded:
            add(name, EXCLUDED, "rule: " + rule_excluded[name].why, src.vars[name], None, rule_excluded[name])
        elif name not in alias_sources:
            add(name, LOST, f"{target.ecm_id} has no such variable", src.vars[name], None)
    for name in plan.dst_only:
        if name in handled:
            ruled.append(name)
        else:
            add(name, TARGET_ONLY, "", None, dst.vars[name])

    # Rules 6 and 8: variables that share target bytes, and maps with their
    # axes, are copied together or not at all.
    groups = _Groups()
    for name in dst.vars:
        groups.find(name)
    spans = sorted((dst.position(v), dst.position(v) + v.size, v.name) for v in dst.vars.values())
    overlaps: set[tuple[str, str]] = set()
    for i, (s1, e1, n1) in enumerate(spans):
        for s2, e2, n2 in spans[i + 1:]:
            if s2 >= e1:
                break
            groups.union(n1, n2)
            overlaps |= {(n1, n2), (n2, n1)}
    for v in dst.vars.values():
        if v.type == "Map":
            for ax in dst.axis_refs(v):
                if ax:
                    groups.union(v.name, ax)
    candidate_set, ruled_set = set(candidates), set(ruled)
    blocked: dict[str, str] = {}
    for members in groups.members().values():
        if len(members) == 1:
            continue
        movers = [m for m in members if m in candidate_set or m in ruled_set]
        outside = [m for m in members if m not in candidate_set and m not in ruled_set]
        if outside:
            for m in movers:
                blocked[m] = f"belongs together with {', '.join(sorted(outside))}, which isn't copied"
            continue
        for m in members:
            if m in ruled_set and any((m, n) in overlaps for n in members):
                for n in members:
                    blocked[n] = f"{m} is written by a rule and shares bytes with other variables"
        # Overlapping members must overlap the same way in the source, and
        # bitfields can't be partly copied inside a group.
        for a in members:
            for b in members:
                if a < b and a in candidate_set and b in candidate_set and (a, b) in overlaps and (
                        src.position(src.vars[a]) - src.position(src.vars[b])
                        != dst.position(dst.vars[a]) - dst.position(dst.vars[b])):
                    for m in members:
                        blocked[m] = f"{a} and {b} overlap differently in the two layouts"
        for m in members:
            v = dst.vars[m]
            if v.type == "Bits" and undescribed_bits(db, v) and m not in blocked:
                for n in members:
                    blocked[n] = f"bitfield {m} shares bytes with other variables"

    # Write. Every write is recorded per bit, so two writers can't collide
    # and the verification can check that nothing else changed.
    data = bytearray(target.data)
    written = bytearray(len(data))  # bit mask per byte
    owner: dict[int, str] = {}

    def write(start: int, raw: bytes, who: str, mask: int = 0xFF):
        for i, b in enumerate(raw):
            pos = start + i
            if (data[pos] ^ b) & written[pos] & mask:
                raise RuleError(f"{who} would change bits that {owner[pos]} already wrote (byte {pos})")
            data[pos] = (data[pos] & ~mask & 0xFF) | (b & mask)
            written[pos] |= mask
            owner[pos] = who

    def finish(a: Action, how: str):
        a.how = how
        same = bytes(data[target.start(a.var_t):target.start(a.var_t) + a.var_t.size]) == target.raw(a.var_t)
        a.action = EQUAL if same else COPIED

    for name in candidates:
        vs, vt = src.vars[name], dst.vars[name]
        if name in blocked:
            add(name, KEPT, blocked[name], vs, vt, copy_ok.get(name))
            continue
        a = add(name, COPIED, "rule: " + copy_ok[name].why if name in copy_ok else "", vs, vt, copy_ok.get(name))
        s_raw, t_start = source.raw(vs), target.start(vt)
        if vt.type == "Bits":
            mask = _described_mask(db, vt)
            for i, b in enumerate(s_raw):
                diff = (target.data[t_start + i] ^ b) & ~mask & 0xFF
                a.bits_kept += [bit + 1 for bit in range(8) if diff >> bit & 1]
            write(t_start, s_raw, name, mask)
        else:
            write(t_start, s_raw, name)
        finish(a, RAW)

    for name in ruled:
        r = handled[name]
        vs, vt = src.vars[r.source.name], dst.vars[name]
        label = f"{r.source.name} → {name}" if r.source.name != name else name
        if name in blocked:
            add(name, KEPT, blocked[name], vs, vt, r)
            continue
        if not source.available(vs) or not target.available(vt):
            add(name, KEPT, "not in both images (no page 0)", vs, vt, r)
            continue
        a = add(name, COPIED, "", vs, vt, r)
        t_start = target.start(vt)
        if r.kind == ALIAS:
            a.reason = f"alias of {r.source.name}"
            diffs = definition_differences(vs, src, vt, dst)
            if vs.type == "Map" and vt.type == "Map":
                renamed = {h.source.name: n for n, h in handled.items() if h.kind == ALIAS}
                mapped = tuple(renamed.get(ax, ax) if ax else None for ax in src.axis_refs(vs))
                if mapped == dst.axis_refs(vt):
                    diffs = [d for d in diffs if not d.startswith("axes ")]
            shape = [d for d in diffs if not d.startswith(_SCALE_ATTRS)]
            if shape:
                a.action, a.reason = KEPT, f"alias of {r.source.name}, but the definitions differ: {'; '.join(shape)}"
                continue
            if not diffs:
                if vt.type == "Bits":
                    write(t_start, source.raw(vs), label, _described_mask(db, vt) & _described_mask(db, vs))
                else:
                    write(t_start, source.raw(vs), label)
                finish(a, RAW)
                continue
            ints = [encode_element(vt, i, x) for i, x in enumerate(a.source)]
            if None in ints:
                bad = a.source[ints.index(None)]
                a.action, a.reason = KEPT, f"alias of {r.source.name}: {bad} doesn't fit {name}"
                continue
            a.reason += f", converted to scale {vt.scale}"
            write(t_start, pack_ints(vt, ints), label)
            finish(a, SCALED)
        elif r.transform == COPY_ELEMENTS:
            a.reason = r.describe()
            w = vs.width
            chunk = source.raw(vs)[r.source_start * w:(r.source_start + r.count) * w]
            write(t_start + r.target_start * w, chunk, label)
            finish(a, ELEMENTS)
        else:  # resample_pairs
            values, why = _resample(vs, a.source, vt, a.before)
            if values is None:
                a.action, a.reason = KEPT, f"{RESAMPLE_PAIRS}: {why}"
                continue
            ints = element_ints(vt, target.raw(vt))
            for i in range(1, len(values), 2):
                ints[i] = encode_element(vt, i, values[i])
            if None in ints:
                a.action, a.reason = KEPT, f"{RESAMPLE_PAIRS}: a value doesn't fit {name}"
                continue
            a.reason, a.expected = f"{RESAMPLE_PAIRS} onto the target's axis", values
            raw = pack_ints(vt, ints)
            for i in range(1, len(ints), 2):  # values only; the axis stays the target's
                write(t_start + i * vt.width, raw[i * vt.width:(i + 1) * vt.width], label)
            finish(a, RESAMPLED)

    for r, i in bit_rules:
        t = r.targets[i]
        vs, vt = src.vars[r.source.name], dst.vars[t.name]
        name = str(t)
        a = add(name, COPIED, f"alias of {r.source}", vs, vt, r)
        a.how, a.bit = BIT, (r.source.bit, t.bit)
        if not source.available(vs) or not target.available(vt):
            a.action, a.reason = KEPT, "not in both images (no page 0)"
            continue
        if t.name in blocked:
            a.action, a.reason = KEPT, blocked[t.name]
            continue
        sbit = source.raw(vs)[0] >> (r.source.bit - 1) & 1
        tmask = 1 << (t.bit - 1)
        if written[target.start(vt)] & tmask:
            raise RuleError(f"{r.where}: {t} is already written by {owner[target.start(vt)]}")
        before = target.raw(vt)[0] & tmask
        write(target.start(vt), bytes([tmask if sbit else 0]), f"{r.source} → {t}", tmask)
        a.source, a.before = [sbit], [1 if before else 0]
        a.action = EQUAL if bool(before) == bool(sbit) else COPIED

    result = image_from_bytes(db, bytes(data), target.ecm_id)
    for a in actions.values():
        if a.var_t is not None and result.available(a.var_t):
            if a.how == BIT:
                a.after = [result.raw(a.var_t)[0] >> (a.bit[1] - 1) & 1]
            else:
                a.after = result.physical(a.var_t)

    problems = _verify(db, source, target, result, actions, written)

    changed_pages = {}
    for page in dst.pages:
        if page.start + page.size > len(data):
            continue
        n = sum(1 for i in range(page.start, page.start + page.size) if result.data[i] != target.data[i])
        if n:
            changed_pages[page.nr] = n
    return Conversion(plan, source, target, result, actions, mismatch, changed_pages, problems,
                      pair, allow_proposed, applied, pending, skipped)


def _verify(db: Database, source: Image, target: Image, result: Image, actions: dict[str, Action],
            written: bytearray) -> list[str]:
    """Check the result against the source and the target, independently of
    how it was written: every copied variable holds the source's value in
    the way its rule says, and every bit nobody wrote is the target's."""
    problems = []
    if len(result.data) != len(target.data):
        problems.append(f"result has {len(result.data)} bytes, target {len(target.data)}")
    for a in actions.values():
        if a.action not in (COPIED, EQUAL):
            continue
        vs, vt = a.var_s, a.var_t
        r, s = result.raw(vt), source.raw(vs)
        if a.how == RAW:
            mask = _described_mask(db, vt) if vt.type == "Bits" else 0xFF
            if vt.type == "Bits" and vs.name != vt.name:
                mask &= _described_mask(db, vs)
            if len(r) != len(s) or any((x ^ y) & mask for x, y in zip(r, s)):
                problems.append(f"{a.name}: bytes differ from the source")
        elif a.how == SCALED:
            for i, (x, y) in enumerate(zip(result.physical(vt), source.physical(vs))):
                if abs(x - y) > element_scale(vt, i)[0] / 2 + 1e-9:
                    problems.append(f"{a.name}[{i}]: {x} is more than half a step from the source's {y}")
        elif a.how == ELEMENTS:
            rule = a.rule
            se = element_ints(vs, s)[rule.source_start:rule.source_start + rule.count]
            re_ = element_ints(vt, r)[rule.target_start:rule.target_start + rule.count]
            if se != re_:
                problems.append(f"{a.name}: copied elements differ from the source")
        elif a.how == RESAMPLED:
            got, before = result.physical(vt), target.physical(vt)
            for i in range(0, len(got) - 1, 2):
                if got[i] != before[i]:
                    problems.append(f"{a.name}: axis point {i // 2 + 1} changed")
                if abs(got[i + 1] - a.expected[i + 1]) > element_scale(vt, i + 1)[0] / 2 + 1e-9:
                    problems.append(f"{a.name}: value {i // 2 + 1} is {got[i + 1]}, expected {a.expected[i + 1]}")
        elif a.how == BIT:
            sb, tb = a.bit
            if (s[0] >> (sb - 1) & 1) != (r[0] >> (tb - 1) & 1):
                problems.append(f"{a.name}: bit differs from {vs.name}[{sb}]")
    for i, (x, y) in enumerate(zip(result.data, target.data)):
        if (x ^ y) & ~written[i] & 0xFF:
            problems.append(f"byte {i} changed although nothing wrote it")
    return problems
