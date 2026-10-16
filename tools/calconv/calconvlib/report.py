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
"""Markdown and JSON output for the calconv commands."""

from __future__ import annotations

import json

from .analysis import Plan
from .db import Database, Layout, VarDef
from .diff import CHANGED, EQUAL, MISSING_A, MISSING_B, ONLY_A, ONLY_B, Diff, Entry
from .image import Image, ecm_info, format_value, format_values
from .rules import CommonRules

HIDDEN = "(hidden, use --show-private)"
MAX_CELLS = 8  # list at most this many differing cells of a table or map


def _md_cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in rows]
    return out


def _pct(part: int, total: int) -> str:
    return f"{part}/{total} ({100.0 * part / total:.1f}%)" if total else "–"


def _label(var: VarDef | None) -> str:
    return (var.label or "") if var else ""


def _dump(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _layout_name(lay: Layout, ecm_id: str) -> str:
    others = [i for i in lay.ids if i != ecm_id]
    return ecm_id + (f" (same layout: {', '.join(others)})" if others else "")


# --- layouts ---------------------------------------------------------------

def layouts(db: Database, fmt: str) -> str:
    lays = db.layouts()
    if fmt == "json":
        return _dump([{
            "ids": lay.ids, "category": lay.category, "family": lay.family,
            "xpr_size": lay.xsize, "epr_size": lay.size, "page0_size": lay.page0_size,
            "pages": len([p for p in lay.pages if p.nr != 0]), "variables": len(lay.vars),
            "remarks": lay.remarks, "warnings": lay.warnings,
        } for lay in lays])
    out = ["# ECM layouts", "", f"Database: `{db.path}`", ""]
    rows = []
    for lay in sorted(lays, key=lambda l: (l.family, l.ids[0])):
        rows.append([", ".join(lay.ids), lay.family, lay.xsize, lay.size, lay.page0_size,
                     len([p for p in lay.pages if p.nr != 0]), len(lay.vars),
                     " / ".join(sorted(set(lay.remarks.values())))])
    out += _table(["ECM IDs", "Family", ".xpr bytes", ".epr bytes", "Page 0 bytes", "Pages", "Variables",
                   "Description"], rows)
    by_size: dict[int, list[str]] = {}
    for lay in lays:
        for size, kind in ((lay.xsize, ".xpr"), (lay.size, ".epr")):
            entry = "/".join(lay.ids) + f" {kind}"
            if entry not in by_size.setdefault(size, []):
                by_size[size].append(entry)
    shared = {s: e for s, e in by_size.items() if len({x.rsplit(' ', 1)[0] for x in e}) > 1}
    if shared:
        out += ["", "File sizes that fit more than one layout (give the ECM ID when loading such a file):", ""]
        out += [f"- {s} bytes: {', '.join(e)}" for s, e in sorted(shared.items())]
    return "\n".join(out) + "\n"


# --- plan ------------------------------------------------------------------

def plan(p: Plan, fmt: str, show_all: bool = False) -> str:
    excluded_by = {}
    for reason in p.excluded.values():
        excluded_by[reason] = excluded_by.get(reason, 0) + 1
    excl_identical = {n: r for n, r in p.excluded.items() if n not in p.different}
    if fmt == "json":
        return _dump({
            "source": {"id": p.src_id, "same_layout": p.src.ids, "family": p.src.family,
                       "xpr_size": p.src.xsize, "variables": len(p.src.vars)},
            "target": {"id": p.dst_id, "same_layout": p.dst.ids, "family": p.dst.family,
                       "xpr_size": p.dst.xsize, "variables": len(p.dst.vars)},
            "same_family": p.same_family,
            "same_layout": p.same_layout,
            "counts": {
                "shared": len(p.shared), "same_offset": p.same_offset, "identical": len(p.identical), "different": len(p.different),
                "source_only": len(p.src_only), "target_only": len(p.dst_only),
                "copyable": len(p.copyable), "excluded_identical": len(excl_identical),
                "bitfields": len(p.bitfields), "bitfields_undescribed": len(p.bitfields_undescribed),
                "rename_candidates": len(p.candidates),
            },
            "copyable": p.copyable,
            "excluded": p.excluded,
            "different": p.different,
            "source_only": p.src_only,
            "target_only": p.dst_only,
            "bitfields_undescribed": p.bitfields_undescribed,
            "rename_candidates": {s: [{"target": c.target, "score": c.score, "signals": c.signals} for c in cs]
                                  for s, cs in p.candidates.items()},
            "semantic_warnings": p.semantic,
            "model_guard": p.model_guard,
            "database_warnings": p.warnings,
            "coverage": {k: {"covered": c, "total": t} for k, (c, t) in p.coverage.items()},
        })

    s, d = p.src_id, p.dst_id
    out = [f"# Conversion plan: {s} → {d}", "",
           f"- Source: {_layout_name(p.src, s)}, {p.src.family}, .xpr {p.src.xsize} bytes",
           f"- Target: {_layout_name(p.dst, d)}, {p.dst.family}, .xpr {p.dst.xsize} bytes", ""]
    if not p.same_family:
        out += [f"> **Different families ({p.src.family} → {p.dst.family}). Converting between them isn't "
                "supported.** The analysis below is for information only.", ""]
    if p.same_layout:
        out += ["> Both IDs share one layout: a file can be loaded as it is, no conversion needed.", ""]
    reasons = ", ".join(f"{r}: {n}" for r, n in sorted(excluded_by.items()))
    cov = "; ".join(f"{k} {_pct(c, t)}" for k, (c, t) in p.coverage.items())
    out += ["## Summary", ""]
    out += _table(["Group", "Count", "Handling"], [
        [f"Variables in {s}", len(p.src.vars), ""],
        [f"Variables in {d}", len(p.dst.vars), ""],
        ["Shared names", len(p.shared), f"{p.same_offset} at the same offset in both layouts"],
        ["…identical definition", len(p.identical),
         f"copy {len(p.copyable)}; never copied: {len(excl_identical)}"],
        ["…different definition", len(p.different), "keep the target's value and review"],
        [f"Only in {s}", len(p.src_only), f"lost: {d} has no such variable"],
        [f"Only in {d}", len(p.dst_only), "keep the target's value"],
        ["Excluded shared names (all)", len(p.excluded), reasons or "–"],
        ["Copyable bitfields", len(p.bitfields),
         f"{len(p.bitfields_undescribed)} with undescribed bits: copy only the described bits"],
        ["Rename candidates", len(p.candidates), "review; never applied automatically"],
        ["Bytes described by variables", "", cov + ". The rest keeps the target's value."],
    ])

    out += ["", "## Needs attention", ""]
    if p.semantic:
        out += ["### Meaning may depend on the firmware", "",
                "The database description mentions firmware versions. Don't copy these by name "
                "without checking what each firmware does with them.", ""]
        out += [f"- **{n}**: {t}" for n, t in p.semantic.items()] + [""]
    if p.different:
        out += ["### Same name, different definition", ""]
        out += _table(["Variable", "Label", "Differences"],
                      [[n, _label(p.src.vars[n]), "; ".join(diffs)] for n, diffs in p.different.items()])
        out += [""]
    if p.src_only:
        out += [f"### Only in {s} (lost on {d})", ""]
        out += _table(["Variable", "Type", "Label"],
                      [[n, p.src.vars[n].type, _label(p.src.vars[n])] for n in p.src_only])
        out += [""]
    if p.dst_only:
        out += [f"### Only in {d} (the target's values are kept)", ""]
        out += _table(["Variable", "Type", "Label"],
                      [[n, p.dst.vars[n].type, _label(p.dst.vars[n])] for n in p.dst_only])
        out += [""]
    if p.candidates:
        out += ["### Rename candidates", "",
                "Possible renames between the two layouts. A person decides; confirmed ones become rules.", ""]
        rows = []
        for src_name, cands in p.candidates.items():
            for c in cands:
                rows.append([src_name, c.target, c.score, ", ".join(c.signals)])
        out += _table([f"{s} variable", f"{d} candidate", "Score", "Signals"], rows) + [""]
    if p.model_guard:
        out += ["### Model guard", "",
                "These describe the engine and harness. Compare the values of both images before converting "
                "(`calconv info`).", ""]
        out += [f"- {n}: {st}" for n, st in p.model_guard.items()] + [""]
    for ecm_id, warns in p.warnings.items():
        if warns:
            out += [f"### Database warnings: {ecm_id}", ""] + [f"- {w}" for w in warns] + [""]

    if show_all:
        out += ["## Copyable variables", ""]
        out += _table(["Variable", "Type", "Label"], [[n, p.src.vars[n].type, _label(p.src.vars[n])]
                                                       for n in p.copyable]) + [""]
        out += ["## Never copied", ""]
        out += _table(["Variable", "Reason"], [[n, r] for n, r in p.excluded.items()]) + [""]
        if p.bitfields_undescribed:
            out += ["## Bitfields with undescribed bits", "",
                    "Only the described bits would be copied; the others keep the target's value.", ""]
            out += _table(["Variable", "Undescribed bits"],
                          [[n, ", ".join(map(str, b))] for n, b in p.bitfields_undescribed.items()]) + [""]
    else:
        out += ["Use `--all` to list the copyable and excluded variables.", ""]
    return "\n".join(out).rstrip() + "\n"


# --- info ------------------------------------------------------------------

def _bits_set(db: Database, var: VarDef, value: int) -> list[str]:
    labels = db.bit_labels(var.name)
    return [labels[i] or f"bit {i + 1}" for i in range(8) if value & (1 << i)]


def info(db: Database, img: Image, rules: CommonRules, show_private: bool, fmt: str) -> str:
    fields = ecm_info(img)
    guard = {}
    for name in rules.model_guard:
        var = img.var(name)
        if var is None or not img.available(var):
            continue
        value = img.values(var)[0]
        guard[name] = {"value": format_value(var, value),
                       "bits_set": _bits_set(db, var, value) if var.type == "Bits" else []}
    priv = {}
    for name in rules.private:
        var = img.var(name)
        if var is not None and img.available(var):
            priv[name] = format_values(var, img.physical(var)) if show_private else HIDDEN
    data = {
        "file": img.name, "bytes": len(img.data), "kind": img.kind, "has_page0": img.has_page0,
        "ecm_id": img.ecm_id, "same_layout": img.same_layout_ids(), "family": img.layout.family,
        **fields, "model_guard": guard, "private": priv,
    }
    if fmt == "json":
        return _dump(data)
    kind = ".xpr, with page 0" if img.has_page0 else (
        ".epr, without page 0" if img.layout.page0_size else "no page 0 in this layout")
    out = [f"# {img.name}", ""]
    out += _table(["Field", "Value"], [
        ["Size", f"{len(img.data)} bytes ({kind})"],
        ["ECM ID", _layout_name(img.layout, img.ecm_id)],
        ["Family", img.layout.family],
        ["Layout revision (CSR)", fields["layout_revision"] or "–"],
        ["Country ID", fields["country_id"] or "–"],
        ["Calibration ID", fields["calibration_id"] or "–"],
        ["Serial number", fields["serial_no"] or "–"],
        ["Manufacturing date", fields["mfg_date"] or "–"],
    ])
    if guard:
        out += ["", "## Model guard", ""]
        out += _table(["Variable", "Value", "Bits set"],
                      [[n, g["value"], "; ".join(g["bits_set"]) or "–"] for n, g in guard.items()])
    if priv:
        out += ["", "## Private data", ""]
        out += _table(["Variable", "Value"], [[n, v] for n, v in priv.items()])
    return "\n".join(out) + "\n"


# --- diff ------------------------------------------------------------------

def _cell_name(var: VarDef, i: int) -> str:
    if var.type == "Map" and var.cols:
        r, c = divmod(i, var.cols + (var.skip or 0))  # DDFI-2 fuel maps skip a byte per row
        return f"[{r},{c}]" if c < var.cols else f"[{r},skipped]"
    if var.type == "Table":
        return f"[{i // 2},{'axis' if i % 2 == 0 else 'value'}]"
    return f"[{i}]"


def _change_text(e: Entry, show_private: bool) -> tuple[str, str]:
    if e.private and not show_private:
        return HIDDEN, HIDDEN
    va, vb = e.var_a, e.var_b
    n = max(len(e.values_a or []), len(e.values_b or []))
    if n <= MAX_CELLS or e.definition:
        return format_values(va, e.values_a), format_values(vb, e.values_b)
    cells = e.changed_cells
    shown = []
    for i in cells[:MAX_CELLS]:
        a = format_value(va, e.values_a[i], i) if i < len(e.values_a) else "–"
        b = format_value(vb, e.values_b[i], i) if i < len(e.values_b) else "–"
        shown.append(f"{_cell_name(va, i)} {a}→{b}")
    more = f", … ({len(cells) - MAX_CELLS} more)" if len(cells) > MAX_CELLS else ""
    return f"{len(cells)} of {n} cells differ", "; ".join(shown) + more


def diff(d: Diff, fmt: str, show_private: bool = False, show_all: bool = False) -> str:
    def side(img: Image) -> dict:
        return {"file": img.name, "ecm_id": img.ecm_id, "kind": img.kind, "has_page0": img.has_page0}

    if fmt == "json":
        def values(e: Entry, vals):
            return HIDDEN if e.private and not show_private else vals
        return _dump({
            "a": side(d.a), "b": side(d.b), "identical": d.identical,
            "counts": {st: len(d.by_status(st)) for st in (EQUAL, CHANGED, ONLY_A, ONLY_B, MISSING_A, MISSING_B)},
            "bytes": None if d.bytes is None else {
                "pages": d.bytes.pages, "page0": d.bytes.page0, "uncovered": d.bytes.uncovered,
                "uncovered_offsets": d.bytes.uncovered_offsets},
            "entries": [{
                "name": e.name, "status": e.status, "label": _label(e.var),
                "a": values(e, e.values_a), "b": values(e, e.values_b),
                "changed_cells": e.changed_cells, "definition": e.definition,
            } for e in d.entries if show_all or e.status != EQUAL],
        })

    out = ["# Image comparison", "",
           f"- A: `{d.a.name}`: {_layout_name(d.a.layout, d.a.ecm_id)}, {d.a.kind}",
           f"- B: `{d.b.name}`: {_layout_name(d.b.layout, d.b.ecm_id)}, {d.b.kind}", ""]
    rows = [[st, len(d.by_status(st))] for st in (EQUAL, CHANGED, ONLY_A, ONLY_B, MISSING_A, MISSING_B)]
    out += _table(["Variables", "Count"], rows)
    if d.bytes is not None:
        b = d.bytes
        out += ["", "Raw bytes (same layout):", "",
                f"- pages 1…n: {b.pages} byte(s) differ",
                f"- page 0: " + ("not in both images" if b.page0 is None else f"{b.page0} byte(s) differ"),
                f"- outside any variable: {b.uncovered} byte(s) differ"
                + (f" (offsets {', '.join(map(str, b.uncovered_offsets[:20]))}"
                   + (", …" if len(b.uncovered_offsets) > 20 else "") + ")" if b.uncovered_offsets else "")]
    out += ["", "**The images are identical.**" if d.identical else "**The images differ.**"]

    changed = d.by_status(CHANGED)
    if changed:
        out += ["", "## Changed", ""]
        rows = []
        for e in changed:
            a, b = _change_text(e, show_private)
            note = ("; definition: " + "; ".join(e.definition)) if e.definition else ""
            rows.append([e.name + (" (page 0)" if e.var.in_page0 else ""), _label(e.var) + note, a, b])
        out += _table(["Variable", "Label", "A", "B"], rows)
    for status, title in ((ONLY_A, "Only in A"), (ONLY_B, "Only in B"),
                          (MISSING_A, "Not in image A (no page 0)"), (MISSING_B, "Not in image B (no page 0)")):
        entries = d.by_status(status)
        if entries:
            out += ["", f"## {title}", ""]
            out += _table(["Variable", "Label"], [[e.name, _label(e.var)] for e in entries])
    if show_all:
        equal = d.by_status(EQUAL)
        if equal:
            out += ["", "## Equal", ""]
            out += _table(["Variable", "Label", "Value"], [
                [e.name, _label(e.var), HIDDEN if e.private and not show_private
                 else format_values(e.var_a, e.values_a)] for e in equal])
    return "\n".join(out) + "\n"


# --- convert ---------------------------------------------------------------

def _cells(a, b) -> list[int]:
    if a is None or b is None:
        return []
    return [i for i in range(max(len(a), len(b))) if i >= len(a) or i >= len(b) or a[i] != b[i]]


def _before_after(var: VarDef, before, after) -> tuple[str, str]:
    n = max(len(before or []), len(after or []))
    if n <= MAX_CELLS:
        return format_values(var, before), format_values(var, after)
    cells = _cells(before, after)
    shown = [f"{_cell_name(var, i)} {format_value(var, before[i], i)}→{format_value(var, after[i], i)}"
             for i in cells[:MAX_CELLS]]
    more = f", … ({len(cells) - MAX_CELLS} more)" if len(cells) > MAX_CELLS else ""
    return f"{len(cells)} of {n} cells changed", "; ".join(shown) + more


def conversion(c, out_path, fmt: str, show_all: bool = False) -> str:
    from .analysis import coverage
    from .convert import COPIED, EQUAL, EXCLUDED, KEPT, LOST, TARGET_ONLY

    s, t = c.source, c.target
    covered, total = coverage(t.layout)
    order = (COPIED, EQUAL, KEPT, EXCLUDED, LOST, TARGET_ONLY)
    counts = {k: len(c.by_action(k)) for k in order}
    if fmt == "json":
        return _dump({
            "source": {"file": s.name, "ecm_id": s.ecm_id}, "target": {"file": t.name, "ecm_id": t.ecm_id},
            "output": str(out_path), "verified": not c.problems, "problems": c.problems,
            "model_mismatch_allowed": c.model_mismatch, "counts": counts,
            "changed_pages": c.changed_pages,
            "undescribed_target_bytes": total - covered,
            "actions": [{
                "name": a.name, "label": _label(a.var), "action": a.action, "reason": a.reason,
                "source": a.source, "before": a.before, "after": a.after, "bits_kept": a.bits_kept,
            } for a in c.actions.values() if show_all or a.action != EQUAL],
        })

    out = [f"# Conversion: {s.ecm_id} → {t.ecm_id}", "",
           f"- Source (tune): `{s.name}`, {_layout_name(s.layout, s.ecm_id)}",
           f"- Target (ECM image): `{t.name}`, {_layout_name(t.layout, t.ecm_id)}",
           f"- Result: `{out_path}`, {len(c.result.data)} bytes, {t.ecm_id} layout", ""]
    if c.problems:
        out += ["> **Verification failed. Don't use the result.**", ""] + [f"- {p}" for p in c.problems] + [""]
    else:
        out += ["Verified: every copied variable holds the source's bytes (described bits only for "
                "bitfields), and every other byte is the target's.", ""]
    if c.model_mismatch:
        out += ["> **Model guard overridden** (`--allow-model-mismatch`): "
                + "; ".join(f"{n} source {a} / target {b}" for n, (a, b) in c.model_mismatch.items()), ""]
    out += ["## Summary", ""]
    out += _table(["Variables", "Count", "Meaning"], [
        ["copied", counts[COPIED], "the result has the tune's value"],
        ["already equal", counts[EQUAL], "copyable, and the target already had the tune's value"],
        ["kept (review)", counts[KEPT], "shared, but the target's value is kept; see below"],
        ["excluded", counts[EXCLUDED], "never copied: page 0, identification, per-unit values, model guard"],
        [f"lost (only in {s.ecm_id})", counts[LOST], f"{t.ecm_id} has no such setting"],
        [f"only in {t.ecm_id}", counts[TARGET_ONLY], "the target's value is kept"],
    ])
    out += ["", f"{total - covered} of the target's {total} bytes aren't described by the database and keep "
            "the target's value. Some of them can be calibration data that a tune changes (e.g. the "
            "undescribed rows right before `Tab_Spark_Front` on DDFI-3).", ""]
    pages = ", ".join(f"{p}: {n}" for p, n in sorted(c.changed_pages.items())) or "none"
    out += [f"Bytes that differ from the target, per page: {pages}.", ""]

    kept = c.by_action(KEPT)
    if kept:
        out += ["## Kept: needs review", "",
                "The target's value is kept. Decide each one: leave it, or set it by hand after burning.", ""]
        rows = []
        for a in kept:
            rows.append([a.name, _label(a.var), a.reason, format_values(a.var_s, a.source),
                         format_values(a.var_t, a.before)])
        out += _table(["Variable", "Label", "Why", "Tune (source)", "Kept (target)"], rows) + [""]
    bits = [a for a in c.actions.values() if a.bits_kept]
    if bits:
        out += ["## Bitfields: undescribed bits kept", "",
                "Only described bits were copied. These undescribed bits differ, and the target's bits were kept.",
                ""]
        out += _table(["Variable", "Label", "Bits", "Tune", "Result"],
                      [[a.name, _label(a.var), ", ".join(map(str, a.bits_kept)),
                        format_values(a.var_s, a.source), format_values(a.var_t, a.after)] for a in bits]) + [""]
    lost = c.by_action(LOST)
    if lost:
        out += [f"## Lost: settings {t.ecm_id} doesn't have", "",
                "The tune's values for these can't be carried over. Check whether the tune relies on them.", ""]
        out += _table(["Variable", "Label", "Tune's value"],
                      [[a.name, _label(a.var), format_values(a.var_s, a.source)] for a in lost]) + [""]
    copied = c.by_action(COPIED)
    if copied:
        out += ["## Copied", ""]
        rows = []
        for a in copied:
            before, after = _before_after(a.var_t, a.before, a.after)
            rows.append([a.name, _label(a.var), before, after])
        out += _table(["Variable", "Label", "Target before", "Result"], rows) + [""]
    if show_all:
        for action, title in ((EQUAL, "Already equal"), (EXCLUDED, "Excluded"), (TARGET_ONLY, f"Only in {t.ecm_id}")):
            rows = [[a.name, _label(a.var), a.reason or "", format_values(a.var_t, a.before)]
                    for a in c.by_action(action)]
            if rows:
                out += [f"## {title}", ""] + _table(["Variable", "Label", "Reason", "Target value"], rows) + [""]
    out += ["## Next steps", "",
            "1. Keep the target image unchanged as a backup.",
            f"2. Load `{out_path}` in EcmDroid (EEPROM → Load) or EcmSpy for Mono, review it, and burn it.",
            f"3. Fetch again, save, and check with `calconv diff {out_path} <fetched.xpr>`: pages 1…n must be equal.",
            "4. Reset both AFVs to 100 % (Setup → AFV Settings): the target's learned AFVs were kept, "
            "but they were learned with the old maps.",
            "5. Start, idle cold and warm, check trouble codes, then a short ride with a log (AFV, EGO correction)."]
    return "\n".join(out) + "\n"
