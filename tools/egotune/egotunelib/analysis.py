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
"""From logs to per-cell corrections (docs/egotune-howto.md).

Every record goes through the same filters as the manual method, plus a few
the manual method can't do in MegaLogViewer: it must be closed loop, warm,
without warm-up/acceleration/deceleration enrichment, and steady for a moment.
The correction the ECM needed is EGO x AFV / 100 (100 % = the map is right);
with the AFV locked at 100 % that's simply the EGO correction. Each record is
spread over the four cells around its operating point with the same bilinear
weights the ECM uses to read the map, and weighted by the time it covers.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from calconvlib.image import Image

from .fuelmap import FuelMap, load_fuel_map
from .runtime import BinLog, RuntimeDefs

# Flags1 bits (table bits): 0 Engine Running, 2 Acceleration, 3 Deceleration, 5 WOT
# Flags2 bit 7: Closed Loop
RUNNING, ACCEL, DECEL, WOT = 0, 2, 3, 5
CLOSED_LOOP = 7


@dataclass(frozen=True)
class Cylinder:
    key: str
    map_name: str
    load: str  # runtime load channel that indexes the map
    ego: str  # EGO correction
    afv: str  # live AFV
    table_fuel: str  # the ECM's own map lookup, raw
    image_afv: str  # stored AFV in the image


CYLINDERS = {
    "front": Cylinder("front", "Tab_Fuel_Front", "FLoad", "FBFuel1", "LFuel1_LD", "TabFuel1_Raw", "LFuel1"),
    "rear": Cylinder("rear", "Tab_Fuel_Rear", "RLoad", "FBFuel", "LFuel_LD", "TabFuel2_Raw", "LFuel"),
}

REQUIRED = ("RPM", "TE", "CrTE", "CrAcc", "Flags1", "Flags2")

# Reasons a record isn't used, in the order they're checked.
REASONS = (
    "engine not running",
    "open loop",
    "cold engine",
    "warm-up enrichment",
    "accel/decel enrichment",
    "transient",
)


@dataclass
class Settings:
    min_te: float = 71.0  # °C (160 °F, as in the manual method)
    max_warmup: float = 0.5  # % of warm-up enrichment (CrTE above 100 %) still accepted
    settle: float = 1.0  # s to skip after a transient or enrichment event
    rpm_rate: float = 1500.0  # rpm/s counted as a transient
    load_rate: float = 40.0  # load units/s counted as a transient
    max_gap: float = 1.0  # s between records counted as a gap (a transient)
    min_seconds: float = 2.0  # data a cell needs before it's changed
    full_seconds: float = 10.0  # data at which a cell gets the full gain
    gain: float = 1 / 3  # part of the correction applied per iteration
    max_rich: float = 6.0  # % a cell may gain per iteration
    max_lean: float = 3.0  # % a cell may lose per iteration
    saturated: float = 0.2  # share of a cell's data at an EGO limit that flags it
    converged: float = 2.0  # % within which every trusted cell counts as done


@dataclass
class CellStat:
    seconds: float = 0.0
    sum_c: float = 0.0  # sum of weight x correction
    sum_c2: float = 0.0
    sat_rich: float = 0.0  # seconds with the EGO correction at its upper limit
    sat_lean: float = 0.0

    def add(self, w: float, c: float, rich: bool, lean: bool):
        self.seconds += w
        self.sum_c += w * c
        self.sum_c2 += w * c * c
        if rich:
            self.sat_rich += w
        if lean:
            self.sat_lean += w

    @property
    def mean(self) -> float:
        return self.sum_c / self.seconds if self.seconds else 100.0

    @property
    def std(self) -> float:
        if not self.seconds:
            return 0.0
        return math.sqrt(max(0.0, self.sum_c2 / self.seconds - self.mean ** 2))

    def saturation(self, share: float) -> str | None:
        """"rich" if the EGO correction sat at its upper limit for at least `share`
        of the cell's data (the ECM added all the fuel it may, so the cell is
        leaner than the mean shows), "lean" for the lower limit."""
        if not self.seconds:
            return None
        if self.sat_rich / self.seconds >= share:
            return "rich"
        if self.sat_lean / self.seconds >= share:
            return "lean"
        return None


@dataclass
class LookupCheck:
    """How well the map lookup reproduces the ECM's logged table fuel value."""

    samples: int = 0
    ratio: float | None = None  # median of logged raw / lookup
    spread: float | None = None  # robust std of log(ratio): 0.01 is about 1 %


@dataclass
class CylinderResult:
    cylinder: Cylinder
    fuel_map: FuelMap
    cells: dict[int, CellStat] = field(default_factory=dict)
    used: int = 0
    active: bool = True
    inactive_reason: str | None = None
    afv_range: tuple[float, float] | None = None  # live AFV while the engine ran
    image_afv: float | None = None
    lookup: LookupCheck = field(default_factory=LookupCheck)

    def stat(self, index: int) -> CellStat:
        return self.cells.get(index) or CellStat()

    def trusted(self, settings: Settings) -> list[int]:
        return [i for i, s in self.cells.items() if s.seconds >= settings.min_seconds]


@dataclass
class LogSummary:
    name: str
    ecm_id: str
    records: int
    bad_checksum: int
    duration: float


@dataclass
class Analysis:
    ecm_id: str
    settings: Settings
    logs: list[LogSummary]
    records: int
    used: int
    excluded: Counter
    cylinders: dict[str, CylinderResult]
    setup: dict[str, float | None]
    warnings: list[str]


def image_setup(img: Image) -> dict[str, float | None]:
    names = ("LFuel", "LFuel1", "KLFuel_Max", "KLFuel_Min", "KFBFuel_Max", "KFBFuel_Min")
    return {n: img.value_of(n) if img.var(n) else None for n in names}


def _robust(xs: list[float]) -> tuple[float, float]:
    xs = sorted(xs)
    n = len(xs)
    median = xs[n // 2]
    iqr = xs[(3 * n) // 4] - xs[n // 4]
    return median, iqr / 1.349


def analyse(img: Image, defs: RuntimeDefs, logs: list[BinLog], settings: Settings | None = None,
            cylinders: tuple[str, ...] = ("front", "rear")) -> Analysis:
    settings = settings or Settings()
    missing = [c for c in REQUIRED if not defs.has(c)]
    for key in cylinders:
        cyl = CYLINDERS[key]
        missing += [c for c in (cyl.load, cyl.ego, cyl.afv) if not defs.has(c)]
    if missing:
        raise ValueError(f"{defs.ecm_id}: runtime channels missing in the database: {', '.join(missing)}")

    setup = image_setup(img)
    ego_max, ego_min = setup["KFBFuel_Max"], setup["KFBFuel_Min"]
    results = {k: CylinderResult(CYLINDERS[k], load_fuel_map(img, CYLINDERS[k].map_name)) for k in cylinders}
    for res in results.values():
        res.image_afv = setup[res.cylinder.image_afv]
    excluded: Counter = Counter()
    ego_values = {k: Counter() for k in cylinders}
    same_as_rear = 0
    afv_seen = {k: [] for k in cylinders}
    ratios = {k: [] for k in cylinders}
    total = used = 0

    for log in logs:
        prev = None
        last_event = -math.inf
        times = [r.time for r in log.records]
        steps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
        typical = steps[len(steps) // 2] if steps else 0.2
        for rec in log.records:
            total += 1
            f, t = rec.frame, rec.time
            rpm = defs.value(f, "RPM")
            dt = typical if prev is None else t - prev.time
            # Transient: a jump in RPM or load, or a gap in the log.
            if prev is None or dt <= 0 or dt > settings.max_gap:
                last_event = t
            else:
                d_rpm = abs(rpm - defs.value(prev.frame, "RPM")) / dt
                d_load = max(abs(defs.value(f, CYLINDERS[k].load) - defs.value(prev.frame, CYLINDERS[k].load))
                             for k in cylinders) / dt
                if d_rpm > settings.rpm_rate or d_load > settings.load_rate:
                    last_event = t
            prev = rec
            weight = min(max(dt, 0.0), settings.max_gap)

            running = defs.bit(f, "Flags1", RUNNING) and rpm >= 500
            if running:
                for key in cylinders:
                    cyl = CYLINDERS[key]
                    afv_seen[key].append(defs.value(f, cyl.afv))
                    if defs.has(cyl.table_fuel):
                        logged = defs.value(f, cyl.table_fuel)
                        expected = results[key].fuel_map.lookup(rpm, defs.value(f, cyl.load))
                        if logged > 0 and expected > 0:
                            ratios[key].append(math.log(logged / expected))

            closed = defs.bit(f, "Flags2", CLOSED_LOOP)
            enrich = (defs.bit(f, "Flags1", ACCEL) or defs.bit(f, "Flags1", DECEL)
                      or defs.value(f, "CrAcc") > 0)
            if not closed or enrich:
                last_event = t  # also restarts the settle time when closed loop begins

            if not running:
                excluded["engine not running"] += 1
            elif not closed or defs.bit(f, "Flags1", WOT):
                excluded["open loop"] += 1
            elif defs.value(f, "TE") < settings.min_te:
                excluded["cold engine"] += 1
            elif defs.value(f, "CrTE") > 100 + settings.max_warmup:
                excluded["warm-up enrichment"] += 1
            elif enrich:
                excluded["accel/decel enrichment"] += 1
            elif t - last_event < settings.settle:
                excluded["transient"] += 1
            else:
                used += 1
                egos = {}
                for key in cylinders:
                    cyl = CYLINDERS[key]
                    ego = defs.value(f, cyl.ego)
                    afv = defs.value(f, cyl.afv)
                    egos[key] = ego
                    ego_values[key][round(ego, 1)] += 1
                    correction = ego * afv / 100.0
                    rich = ego_max is not None and ego >= ego_max - 0.5
                    lean = ego_min is not None and ego <= ego_min + 0.5
                    res = results[key]
                    for idx, w in res.fuel_map.cell_weights(rpm, defs.value(f, cyl.load)):
                        if w > 0:
                            res.cells.setdefault(idx, CellStat()).add(w * weight, correction, rich, lean)
                    res.used += 1
                if "front" in egos and "rear" in egos and abs(egos["front"] - egos["rear"]) < 0.05:
                    same_as_rear += 1

    warnings = []
    for key, res in results.items():
        if afv_seen[key]:
            res.afv_range = (min(afv_seen[key]), max(afv_seen[key]))
        if ratios[key]:
            median, spread = _robust(ratios[key])
            res.lookup = LookupCheck(len(ratios[key]), math.exp(median), spread)
    if "front" in results and used:
        front = results["front"]
        moving = len(ego_values["front"]) > 3
        if not moving:
            front.active = False
            front.inactive_reason = ("the front EGO correction doesn't move: the ECM doesn't run "
                                     "closed loop on the front cylinder")
        elif "rear" in results and same_as_rear >= 0.95 * used:
            front.active = False
            front.inactive_reason = ("the front EGO correction is a copy of the rear one: "
                                     "there's no front O2 feedback to tune from")
    for key, res in results.items():
        if not res.active:
            warnings.append(f"{key}: map left unchanged, {res.inactive_reason}.")
        lo_hi = res.afv_range
        if lo_hi and (abs(lo_hi[0] - 100) > 0.05 or abs(lo_hi[1] - 100) > 0.05):
            warnings.append(f"{key}: the AFV wasn't locked at 100 % during the ride "
                            f"({lo_hi[0]:.1f}-{lo_hi[1]:.1f} %). The corrections include it, "
                            "but lock it for cleaner data (docs/egotune-howto.md, step 1).")
        if lo_hi and res.image_afv is not None and abs(res.image_afv - lo_hi[0]) > 0.5 \
                and abs(lo_hi[1] - lo_hi[0]) <= 0.5:
            warnings.append(f"{key}: the image stores an AFV of {res.image_afv:.1f} %, the log shows "
                            f"{lo_hi[0]:.1f} %. Was this image in the ECM during the ride?")
        lk = res.lookup
        if lk.spread is not None and lk.spread > 0.05:
            warnings.append(f"{key}: the map lookup doesn't follow the ECM's logged table fuel value "
                            f"(spread {100 * lk.spread:.0f} %). Either the image isn't the one that was "
                            "in the ECM during the ride, or the lookup model needs work. Check before burning.")
    if setup["KLFuel_Max"] is not None and (setup["KLFuel_Max"] != 100 or setup["KLFuel_Min"] != 100):
        warnings.append(f"The image's AFV limits are {setup['KLFuel_Min']:g}-{setup['KLFuel_Max']:g} %, "
                        "not locked at 100 %.")
    if total and not used:
        warnings.append("No record passed the filters: nothing to tune from. "
                        "Ride longer with a warm engine in closed loop.")

    summaries = [LogSummary(log.name, log.ecm_id, len(log.records), log.bad_checksum, log.duration)
                 for log in logs]
    return Analysis(img.ecm_id, settings, summaries, total, used, excluded, results, setup, warnings)
