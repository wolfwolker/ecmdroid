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
"""Checks on the whole data set that block `apply` when they fail.

Each check has a name; `--accept NAME` lets apply go ahead anyway, and the
report says so. The filters and per-cell limits keep bad records and cells
out; these checks catch logs that shouldn't be used at all: too little data,
a slow recording, a faulty O2 sensor, corrupted readings, a correction that
points to something outside the maps, the wrong image, or a tune drifting
too far from the original.
"""

from __future__ import annotations

from dataclasses import dataclass

from .analysis import Analysis
from .tune import BASELINE_LIMIT, MapChanges

NAMES = ("short-log", "slow-interval", "o2-switching", "ego-limit", "implausible",
         "global-offset", "lookup", "baseline")


@dataclass
class Check:
    name: str
    passed: bool
    measured: str
    limit: str
    advice: str = ""  # what to do when it fails
    accepted: bool = False

    @property
    def blocking(self) -> bool:
        return not self.passed and not self.accepted


def run_checks(a: Analysis, changes: dict[str, MapChanges], accept: tuple[str, ...] = (),
               has_baseline: bool = False) -> list[Check]:
    s = a.settings
    out = []

    minutes = a.usable_seconds / 60
    out.append(Check("short-log", minutes >= s.min_usable_minutes, f"{minutes:.1f} min usable",
                     f"≥ {s.min_usable_minutes:g} min",
                     "Ride longer after a full warm-up, holding steady throttle in closed loop. "
                     "Several logs can be combined."))

    out.append(Check("slow-interval", a.interval <= s.max_interval, f"{a.interval:.2f} s between records",
                     f"≤ {s.max_interval:g} s",
                     "Record with the interval *No Delay* or 250 ms: transients can't be filtered out "
                     "of slow logs."))

    if a.o2_seconds >= 60:
        rate = a.o2_switches / a.o2_seconds
        out.append(Check("o2-switching", rate >= s.min_o2_switching, f"{rate:.2f} switches/s",
                         f"≥ {s.min_o2_switching:g} /s",
                         "The (rear) O2 sensor hardly switches between rich and lean: it may be worn, "
                         "contaminated, disconnected or its heater may have failed. Check it before tuning."))
    else:
        out.append(Check("o2-switching", False, f"{a.o2_seconds:.0f} s of warm closed loop", "≥ 60 s",
                         "Not enough warm closed-loop data to tell whether the O2 sensor works."))

    active = sorted((r for r in a.cylinders.values() if r.active), key=lambda r: r.cylinder.key != "rear")
    if a.shared_feedback:
        active = active[:1]  # the same (rear) sensor and data for both maps
    seconds = sum(c.seconds for r in active for c in r.cells.values())
    at_limit = sum(c.sat_rich + c.sat_lean for r in active for c in r.cells.values())
    share = 100 * at_limit / seconds if seconds else 0.0
    out.append(Check("ego-limit", share <= s.max_ego_limit, f"{share:.1f} % of the data", f"≤ {s.max_ego_limit:g} %",
                     "The EGO correction sat at its limit: the mixture is far off or the O2 sensor reads "
                     "wrong. Look for exhaust leaks, a faulty sensor or a wrong base map first."))

    bad = a.excluded["implausible reading"]
    share = 100 * bad / a.records if a.records else 0.0
    out.append(Check("implausible", share <= s.max_implausible, f"{bad} records ({share:.1f} %)",
                     f"≤ {s.max_implausible:g} %",
                     "Readings out of range or jumping faster than an engine can: check the sensors, "
                     "the wiring and the adapter connection."))

    worst = None
    for r in active:
        trusted = r.trusted(s)
        weight = sum(r.cells[i].seconds for i in trusted)
        if not weight:
            continue
        mean = sum((r.cells[i].mean - 100) * r.cells[i].seconds for i in trusted) / weight
        same = sum(r.cells[i].seconds for i in trusted if (r.cells[i].mean - 100) * mean > 0) / weight
        if worst is None or abs(mean) > abs(worst[0]):
            worst = (mean, same, r.cylinder.key)
    if worst:
        mean, same, key = worst
        offset = abs(mean) > s.offset_mean and same >= s.offset_share
        out.append(Check("global-offset", not offset,
                         f"{key}: {mean:+.1f} % on average, {100 * same:.0f} % of the data the same way",
                         f"not > {s.offset_mean:g} % with ≥ {100 * s.offset_share:.0f} % the same way",
                         "Nearly the whole map is off in the same direction. That usually has a cause "
                         "outside the maps: an exhaust leak before the O2 sensor (reads falsely lean), fuel "
                         "pressure, a vacuum leak, a fuel change, or an AFV that wasn't locked. Find it "
                         "first; tuning the maps would hide it."))
    else:
        out.append(Check("global-offset", True, "no cell with enough data", "", ""))

    spreads = [(r.cylinder.key, r.lookup.spread) for r in a.cylinders.values() if r.lookup.spread is not None]
    if spreads:
        key, spread = max(spreads, key=lambda x: x[1])
        out.append(Check("lookup", spread <= s.max_lookup_spread, f"{key}: spread {100 * spread:.1f} %",
                         f"≤ {100 * s.max_lookup_spread:g} %",
                         "egotune's map lookup doesn't follow the one the ECM logged. Use the image that "
                         "was in the ECM during the ride (saved right after the last burn). On DDFI-3 this "
                         "check isn't confirmed on a real ride yet."))
    else:
        out.append(Check("lookup", False, "no table fuel data", "", "The log has no table fuel value to check."))

    limited = sum(1 for ch in changes.values() for c in ch.cells.values() if c.state == BASELINE_LIMIT)
    measured = f"{limited} cell(s) at the limit" if has_baseline or limited else "no --baseline given"
    out.append(Check("baseline", limited == 0, measured,
                     f"±{s.max_from_baseline:g} % from the baseline",
                     "These cells want to move further from your original tune than the limit. Accepting "
                     "keeps them at the limit; going further takes --max-from-baseline. Large drifts "
                     "usually point to a problem outside the maps."))

    for c in out:
        c.accepted = c.name in accept and not c.passed
    return out
