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
"""Markdown and JSON reports."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .analysis import REASONS, Analysis, CylinderResult
from .checks import Check
from .tune import BASELINE_LIMIT, CAPPED, NOISY, OUTLIER, MapChanges

TESTING_NOTE = ("egotune is in testing: no map it produced has been burned and ridden yet. "
                "Review every change before you burn it, and keep your original image.")


def _fmt(v: float) -> str:
    return f"{v:g}"


def _grid(res: CylinderResult, cell_text) -> list[str]:
    """A Markdown table over the used cells: load rows (high load at the top), RPM columns."""
    fmap = res.fuel_map
    cols = fmap.rpm.order()
    rows = list(reversed(fmap.load.order()))
    out = ["| Load \\ RPM | " + " | ".join(_fmt(fmap.rpm.values[c]) for c in cols) + " |",
           "|---:|" + "---:|" * len(cols)]
    for r in rows:
        cells = [cell_text(fmap.index(r, c)) for c in cols]
        out.append(f"| **{_fmt(fmap.load.values[r])}** | " + " | ".join(cells) + " |")
    return out


def _cylinder_md(res: CylinderResult, changes: MapChanges | None, a: Analysis) -> list[str]:
    key = res.cylinder.key
    s = a.settings
    out = [f"## {key.capitalize()} cylinder (`{res.cylinder.map_name}`)", ""]
    if res.follows:
        out += [f"Follows the {res.follows} correction cell by cell: {res.inactive_reason}. The grids "
                f"below are the {res.follows} cylinder's data.", ""]
    elif not res.active:
        out += [f"Left unchanged: {res.inactive_reason}.", ""]
    trusted = res.trusted(s)
    stable = res.afv_stable(s)
    if trusted:
        devs = [abs(res.cells[i].mean - 100) for i in trusted]
        weight = sum(res.cells[i].seconds for i in trusted)
        mean_dev = sum(abs(res.cells[i].mean - 100) * res.cells[i].seconds for i in trusted) / weight
        done = ""
        if max(devs) <= s.converged:
            done = (f" — every trusted cell is within ±{_fmt(s.converged)} %"
                    + (": this region is done." if stable else ", but the AFV isn't stable yet (below)."))
        out += [f"- Cells with at least {_fmt(s.min_seconds)} s of data: **{len(trusted)}**",
                f"- Mean deviation from 100 %: **{mean_dev:.1f} %**, largest **{max(devs):.1f} %**" + done]
    else:
        out.append("- No cell has enough data.")
    if res.afv_range:
        lo, hi = res.afv_range
        if hi - lo <= 0.05:
            out.append(f"- AFV during the ride: {lo:.1f} % throughout"
                       + ("" if abs(lo - 100) <= s.converged else
                          ". Fold it into the maps (`egotune fold-afv`) so it starts from 100 %."))
        else:
            out.append(f"- AFV during the ride: {res.afv_first:.1f} % at the start, {res.afv_last:.1f} % at the "
                       f"end ({lo:.1f}–{hi:.1f} %)"
                       + ("" if stable else f". It moved more than {_fmt(s.converged)} %: the closed-loop "
                          "area is still off on average, or the altitude or weather changed."))
    lk = res.lookup
    if lk.spread is not None:
        out.append(f"- Lookup check: {lk.samples} records, logged table fuel / map lookup = "
                   f"{lk.ratio:.2f} × (spread {100 * lk.spread:.1f} %)")
    if changes:
        ch = changes.changed
        rich = sum(1 for c in ch if c.new > c.old)
        capped = sum(1 for c in ch if c.state == CAPPED)
        sat = [c for c in changes.cells.values() if c.saturated]
        out.append(f"- Cells changed: **{len(ch)}** ({rich} richer, {len(ch) - rich} leaner, "
                   f"{capped} limited by the ±cap)")
        fmap = res.fuel_map
        for state, why in ((OUTLIER, "disagree with their neighbours by more than "
                                     f"{_fmt(s.outlier)} points"),
                           (NOISY, f"spread more than {_fmt(s.max_cell_std)} % within the cell"),
                           (BASELINE_LIMIT, f"stopped at ±{_fmt(s.max_from_baseline)} % from the baseline")):
            cells = [c for c in changes.cells.values() if c.state == state]
            if cells:
                where = ", ".join(f"{_fmt(fmap.load.values[fmap.row_col(c.index)[0]])}/"
                                  f"{_fmt(fmap.rpm.values[fmap.row_col(c.index)[1]])}" for c in cells)
                out.append(f"- {len(cells)} cell(s) {state} ({why}), load/rpm: {where}")
        if sat:
            out.append(f"- **{len(sat)} cell(s) hit an EGO correction limit** (marked `!`): the real error "
                       "is bigger than shown. Look at these first.")
    out.append("")

    def corr(i):
        st = res.cells.get(i)
        if not st or st.seconds < 0.05:
            return ""
        txt = f"{st.mean - 100:+.1f}"
        if st.saturation(s.saturated):
            txt += "!"
        return txt if st.seconds >= s.min_seconds else f"_{txt}_"

    if not res.cells:
        return out
    out += [f"### Correction the ECM needed (%, _italic_ = under {_fmt(s.min_seconds)} s of data)", ""]
    out += _grid(res, corr) + [""]
    per_record = a.interval or 0.2
    out += [f"### Data (seconds; {_fmt(s.full_seconds)} s ≈ {s.full_seconds / per_record:.0f} records at "
            f"{per_record:.2f} s per record)", ""]
    out += _grid(res, lambda i: f"{res.cells[i].seconds:.1f}" if i in res.cells and res.cells[i].seconds >= 0.05 else "") + [""]
    if changes:
        def new(i):
            c = changes.cells.get(i)
            if c is None:
                return ""
            if c.new != c.old:
                return f"**{_fmt(c.new)}** ({_fmt(c.old)})"
            return _fmt(c.old)
        out += ["### New map (**new** (old) where it changes)", ""]
        out += _grid(res, new) + [""]
    return out


def _checks_md(checks: list[Check]) -> list[str]:
    out = ["## Checks", "", "| Check | Result | Measured | Limit |", "|---|---|---|---|"]
    for c in checks:
        result = "pass" if c.passed else ("**accepted**" if c.accepted else "**FAIL**")
        out.append(f"| `{c.name}` | {result} | {c.measured} | {c.limit} |")
    out.append("")
    failed = [c for c in checks if not c.passed]
    out += [f"- `{c.name}`: {c.advice}" for c in failed]
    return out + ([""] if failed else [])


def markdown(a: Analysis, changes: dict[str, MapChanges] | None, checks: list[Check], image: Path,
             out: Path | None, blocked: bool = False) -> str:
    s = a.settings
    lines = [f"# Fuel-map corrections: {a.ecm_id}", "", f"> **{TESTING_NOTE}**", ""]
    failed = [c.name for c in checks if c.blocking]
    accepted = [c.name for c in checks if c.accepted]
    if blocked:
        lines += [f"> **Not applied: check(s) failed: {', '.join(failed)}.** Nothing was written. See "
                  "*Checks* below.", ""]
    elif failed:
        lines += [f"> **Check(s) failed: {', '.join(failed)}.** `apply` won't write an image until they "
                  "pass or you accept them (`--accept`).", ""]
    if accepted:
        lines += [f"> **Overridden with --accept: {', '.join(accepted)}.** These checks failed and "
                  "were accepted by the person running egotune.", ""]
    lines += [f"- Image: `{image}`"]
    if out:
        lines.append(f"- Result: `{out}`")
    for log in a.logs:
        bad = f", {log.bad_checksum} with a bad checksum dropped" if log.bad_checksum else ""
        lines.append(f"- Log: `{log.name}` ({log.ecm_id}), {log.records} records, "
                     f"{log.duration / 60:.1f} min{bad}")
    lines.append(f"- Records used: **{a.used}** of {a.records}")
    if a.excluded:
        lines.append("- Left out: " + ", ".join(f"{a.excluded[r]} {r}" for r in REASONS if a.excluded[r]))
    lines.append(f"- Settings: gain {s.gain:.2f}, cells change from {_fmt(s.min_seconds)} s of data with "
                 f"the full gain from {_fmt(s.full_seconds)} s, cap +{_fmt(s.max_rich)} % / "
                 f"−{_fmt(s.max_lean)} % per iteration, settle {_fmt(s.settle)} s")
    lines.append(f"- Warm engine from **{_fmt(s.min_te)} °C** ({a.min_te_source}), with no warm-up "
                 "enrichment left")
    setup = a.setup
    if setup.get("KLFuel_Max") is not None:
        afv = (f"AFV {setup['LFuel']:g} %" if setup.get("LFuel1") is None
               else f"AFV rear {setup['LFuel']:g} %, front {setup['LFuel1']:g} %")
        lines.append(f"- Image setup: {afv}, "
                     f"AFV limits {setup['KLFuel_Min']:g}–{setup['KLFuel_Max']:g} %, "
                     f"EGO limits {setup['KFBFuel_Min']:g}–{setup['KFBFuel_Max']:g} %")
    if a.shared_feedback:
        lines.append("- One O2 sensor (rear cylinder) for both maps: its correction goes into both, "
                     "so the front/rear difference of the tune (the two maps and `Tab_CR_Front`) stays "
                     "as it is.")
    lines.append("")
    lines += _checks_md(checks)
    if a.warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in a.warnings] + [""]
    for key in ("rear", "front"):
        if key in a.cylinders:
            lines += _cylinder_md(a.cylinders[key], (changes or {}).get(key), a)
    lines += ["## Next steps", "",
              "1. Look at the grids: large or isolated changes usually mean bad data, not a bad map.",
              "2. Compare the result with your image: `calconv diff <image> <result>` lists exactly what changed.",
              "3. Burn the result with EcmDroid, *Fetch* and save it, ride again, and run egotune on the new "
              "image and the new log. Stop when every trusted cell stays within "
              f"±{_fmt(s.converged)} % and the AFV stays within ±{_fmt(s.converged)} % of 100 %.", ""]
    return "\n".join(lines)


def as_json(a: Analysis, changes: dict[str, MapChanges] | None, checks: list[Check], image: Path,
            out: Path | None) -> str:
    def cyl(res: CylinderResult):
        fmap = res.fuel_map
        return {
            "map": res.cylinder.map_name,
            "active": res.active,
            "inactive_reason": res.inactive_reason,
            "follows": res.follows,
            "afv_first": res.afv_first,
            "afv_last": res.afv_last,
            "afv_stable": res.afv_stable(a.settings),
            "rpm_axis": fmap.rpm.values[:fmap.rpm.used],
            "load_axis": fmap.load.values[:fmap.load.used],
            "afv_range": res.afv_range,
            "lookup": asdict(res.lookup),
            "cells": [
                {"row": fmap.row_col(i)[0], "col": fmap.row_col(i)[1],
                 "rpm": fmap.rpm.values[fmap.row_col(i)[1]], "load": fmap.load.values[fmap.row_col(i)[0]],
                 "seconds": round(st.seconds, 2), "correction": round(st.mean, 2),
                 "std": round(st.std, 2), "saturated": st.saturation(a.settings.saturated)}
                for i, st in sorted(res.cells.items())],
        }

    doc = {
        "testing_note": TESTING_NOTE,
        "ecm_id": a.ecm_id,
        "image": str(image),
        "result": str(out) if out else None,
        "settings": asdict(a.settings),
        "min_te_source": a.min_te_source,
        "logs": [asdict(log) for log in a.logs],
        "records": a.records,
        "used": a.used,
        "excluded": dict(a.excluded),
        "setup": a.setup,
        "warnings": a.warnings,
        "checks": [{**asdict(c), "blocking": c.blocking} for c in checks],
        "cylinders": {k: cyl(r) for k, r in a.cylinders.items()},
        "changes": {k: [{"index": c.index, "old": c.old, "new": c.new, "state": c.state,
                         "saturated": c.saturated}
                        for c in ch.cells.values() if c.new != c.old]
                    for k, ch in (changes or {}).items()},
    }
    return json.dumps(doc, indent=2) + "\n"
