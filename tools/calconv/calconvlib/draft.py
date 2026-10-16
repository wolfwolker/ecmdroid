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
"""Draft a pair rule file from a plan (`calconv draft-rules`).

Every entry is "proposed": a starting point for a person (or an agent with a
person) to review, never something to apply as it is.
"""

from __future__ import annotations

import json

from .analysis import Plan, definition_differences
from .convert import _scale_compatible, protected_reason
from .db import VarDef
from .rules import CommonRules

_SHAPE = ("size ", "cols ", "rows ")


def _s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)  # a valid TOML basic string


def _wrap(text: str, width: int = 76) -> list[str]:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return lines + ([line] if line else [])


def _suggest(vs: VarDef, vt: VarDef, diffs: list[str]) -> str | None:
    """A transform that fits the definitions, if any."""
    if not all(d.startswith(_SHAPE) for d in diffs) or not _scale_compatible(vs, vt):
        return None
    if vs.type == vt.type == "Table":
        return "resample_pairs"
    if vs.type == vt.type and vs.type not in ("Bits", "String", "Map") and vs.width == vt.width:
        return "copy_elements"
    return None


def draft_rules(plan: Plan, rules: CommonRules) -> str:
    s, d = plan.src_id, plan.dst_id
    out = [f"# Draft rules for converting {s} onto {d}, written by `calconv draft-rules`.",
           "# Every entry is proposed. Check each one against the database descriptions",
           "# and real images, then set status = \"reviewed\" and reviewed_by, or delete it.",
           "# Save as tools/calconv/rules/" + f"{s}-{d}.toml. See docs/calibration-converter.md.",
           "", "[pair]", f"from = {_s(s)}", f"to = {_s(d)}", ""]

    if plan.different or plan.semantic:
        out += ["# --- Same name, different definition or meaning " + "-" * 27, ""]
    for name in list(plan.different) + [n for n in plan.semantic if n not in plan.different]:
        if name in plan.excluded:
            continue
        vs, vt = plan.src.vars[name], plan.dst.vars[name]
        diffs = plan.different.get(name, [])
        if name in plan.semantic:
            out += ["# The description says the meaning depends on the firmware:"]
            out += ["#   " + line for line in _wrap(plan.semantic[name])]
        suggestion = _suggest(vs, vt, diffs) if diffs else None
        if suggestion and name not in plan.semantic:
            out += ["[[transform]]", f"var = {_s(name)}", f"kind = {_s(suggestion)}"]
            if suggestion == "copy_elements":
                out += ["source_start = 0  # check which elements correspond: they may be shifted",
                        f"count = {min(vs.count, vt.count)}"]
            out += [f"evidence = {_s('definitions differ: ' + '; '.join(diffs) + '. TODO: why the values correspond')}",
                    'status = "proposed"', ""]
            continue
        if suggestion:
            out += [f"# A {suggestion} transform would fit the shapes, but check the meaning first."]
        if not diffs:
            out += ["# If the meaning is the same in both firmwares, use [[copy]] instead."]
        reason = ("different definition: " + "; ".join(diffs)) if diffs else "the meaning depends on the firmware"
        out += ["[[exclude]]", f"var = {_s(name)}", f"reason = {_s(reason + '. TODO: confirm')}",
                'status = "proposed"', ""]

    if plan.candidates:
        out += ["# --- Rename candidates (only in one layout) " + "-" * 32, ""]
    # Each target is proposed once, for the source with the best score.
    best_for: dict[str, tuple[float, str]] = {}
    for src_name, cands in plan.candidates.items():
        c = cands[0]
        if c.target not in best_for or c.score > best_for[c.target][0]:
            best_for[c.target] = (c.score, src_name)
    for src_name, cands in plan.candidates.items():
        vs = plan.src.vars[src_name]
        best = cands[0]
        vt = plan.dst.vars[best.target]
        why = protected_reason(best.target, plan.dst, plan, rules) or protected_reason(src_name, plan.src, plan, rules)
        if why:
            out += [f"# {src_name} → {best.target}: never copied ({why})", ""]
            continue
        diffs = definition_differences(vs, plan.src, vt, plan.dst)
        shape = [x for x in diffs if not x.startswith(("scale ", "translate ", "axisscale ", "axistranslate "))]
        others = ", ".join(f"{c.target} ({c.score})" for c in cands[1:])
        labels = f"{vs.label or '–'} / {vt.label or '–'}"
        out += [f"# {src_name} → {best.target}: score {best.score}, labels: {labels}"
                + (f"; other candidates: {others}" if others else "")]
        if shape:
            out += [f"# Not proposed: the definitions differ ({'; '.join(shape)})", ""]
            continue
        if best_for[best.target][1] != src_name:
            out += [f"# Not proposed: {best_for[best.target][1]} is a better match for {best.target}", ""]
            continue
        evidence = ", ".join(best.signals) + (f"; scale differs ({'; '.join(diffs)})" if diffs else "")
        out += ["[[alias]]", f"from = {_s(src_name)}", f"to = {_s(best.target)}",
                f"evidence = {_s(evidence + '. TODO: confirm the meaning')}", 'status = "proposed"', ""]
    if not any(line.startswith("[[") for line in out):
        out += ["# Nothing to decide: every shared variable has the same definition, and",
                "# no entry is proposed for the rename candidates."]
    return "\n".join(out).rstrip() + "\n"
