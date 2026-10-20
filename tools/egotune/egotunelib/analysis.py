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

DDFI-3 has a load, an EGO correction and an AFV per cylinder. DDFI-2 has one
of each: one O2 sensor (in the rear cylinder) whose correction the ECM
applies to both cylinders. Its correction goes into both maps, which keeps
the front/rear difference the tune already has (the two maps and
Tab_CR_Front, the front correction over engine temperature, which the ECM
applies after the map lookup).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from calconvlib.image import Image

from .fuelmap import FuelMap, load_fuel_map
from .runtime import BinLog, RuntimeDefs

# Flags1 bits (table bits): 0 Engine Running, 2 Acceleration, 3 Deceleration, 5 WOT
# Flags2 bits: 6 O2 Rich Voltage, 7 Closed Loop
RUNNING, ACCEL, DECEL, WOT = 0, 2, 3, 5
CLOSED_LOOP = 7
O2_RICH = 6  # Flags2: O2 Rich Voltage


@dataclass(frozen=True)
class Cylinder:
    key: str
    map_name: str
    load: str  # runtime load channel that indexes the map
    ego: str  # EGO correction
    afv: str  # live AFV
    table_fuel: str  # the ECM's own map lookup, raw
    image_afv: str  # stored AFV in the image


DDFI3_CYLINDERS = {
    "front": Cylinder("front", "Tab_Fuel_Front", "FLoad", "FBFuel1", "LFuel1_LD", "TabFuel1_Raw", "LFuel1"),
    "rear": Cylinder("rear", "Tab_Fuel_Rear", "RLoad", "FBFuel", "LFuel_LD", "TabFuel2_Raw", "LFuel"),
}
DDFI2_CYLINDERS = {
    "front": Cylinder("front", "Tab_Fuel_Front", "RLoad", "FBFuel", "LFuel_LD", "TabFuel1_Raw", "LFuel"),
    "rear": Cylinder("rear", "Tab_Fuel_Rear", "RLoad", "FBFuel", "LFuel_LD", "TabFuel2_Raw", "LFuel"),
}


def cylinders_for(defs: RuntimeDefs) -> dict[str, Cylinder]:
    """DDFI-3 logs have a front EGO correction, DDFI-2 logs don't."""
    return DDFI3_CYLINDERS if defs.has("FBFuel1") else DDFI2_CYLINDERS

REQUIRED = ("RPM", "TE", "CrTE", "CrAcc", "Flags1", "Flags2")

# Reasons a record isn't used, in the order they're checked.
REASONS = (
    "implausible reading",
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
    # Per-cell limits (tune.py)
    outlier: float = 8.0  # points a cell may differ from its trusted neighbours
    max_cell_std: float = 10.0  # % spread within a cell before it counts as noisy
    max_from_baseline: float = 15.0  # % a cell may move away from the --baseline image
    # Checks that block apply (checks.py); the healthy BUEIB ride is well inside all of them
    min_usable_minutes: float = 5.0  # warm, steady, closed-loop data
    max_interval: float = 0.5  # s, typical time between records
    min_o2_switching: float = 0.5  # rich/lean switches per second (BUEIB ride: 2.2)
    max_ego_limit: float = 5.0  # % of the data with the EGO correction at a limit
    max_implausible: float = 1.0  # % of the records with implausible readings
    offset_mean: float = 6.0  # % mean correction that, together with...
    offset_share: float = 0.85  # ...this share of the data in one direction, is a global offset
    max_lookup_spread: float = 0.05  # spread of logged table fuel / map lookup


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
    shared_feedback: bool = False  # one O2 sensor for both maps (DDFI-2)
    usable_seconds: float = 0.0  # time covered by the used records
    interval: float = 0.0  # typical time between records (the slowest log)
    o2_seconds: float = 0.0  # warm closed-loop time the O2 switching was watched over
    o2_switches: int = 0  # rich/lean switches of the (rear) O2 sensor in that time


# Physical ranges a running engine stays within, and how fast a value can change.
# A reading outside them comes from a faulty sensor or a corrupted record.
PLAUSIBLE = {
    "RPM": (0.0, 9500.0),
    "TE": (-30.0, 300.0),
    "FBFuel": (40.0, 250.0),
    "FBFuel1": (40.0, 250.0),
    "LFuel_LD": (40.0, 250.0),
    "LFuel1_LD": (40.0, 250.0),
}
MAX_RATE = {"RPM": 20000.0, "TE": 20.0}  # per second


def implausible(defs: RuntimeDefs, frame: bytes, prev: bytes | None, dt: float) -> str | None:
    """The first implausible channel of a record, or None."""
    rpm = defs.value(frame, "RPM")
    running = defs.bit(frame, "Flags1", RUNNING) and rpm >= 500
    for name, (lo, hi) in PLAUSIBLE.items():
        if not defs.has(name) or (name != "RPM" and not running):
            continue
        if not lo <= defs.value(frame, name) <= hi:
            return name
    if prev is not None and 0.05 <= dt <= 1.0:
        for name, rate in MAX_RATE.items():
            if abs(defs.value(frame, name) - defs.value(prev, name)) / dt > rate:
                return name
    return None


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
    cyls = cylinders_for(defs)
    shared = cyls["front"].ego == cyls["rear"].ego
    missing = [c for c in REQUIRED if not defs.has(c)]
    for key in cylinders:
        cyl = cyls[key]
        missing += [c for c in (cyl.load, cyl.ego, cyl.afv) if not defs.has(c)]
    if missing:
        raise ValueError(f"{defs.ecm_id}: runtime channels missing in the database: {', '.join(missing)}")

    setup = image_setup(img)
    ego_max, ego_min = setup["KFBFuel_Max"], setup["KFBFuel_Min"]
    results = {k: CylinderResult(cyls[k], load_fuel_map(img, cyls[k].map_name)) for k in cylinders}
    for res in results.values():
        res.image_afv = setup[res.cylinder.image_afv]
    excluded: Counter = Counter()
    ego_values = {k: Counter() for k in cylinders}
    same_as_rear = 0
    afv_seen = {k: [] for k in cylinders}
    ratios = {k: [] for k in cylinders}
    total = used = 0
    usable_seconds = interval = o2_seconds = 0.0
    o2_switches = 0

    for log in logs:
        prev = None
        prev_cl = None  # the last warm closed-loop record, for the O2 switching
        last_event = -math.inf
        times = [r.time for r in log.records]
        steps = sorted(b - a for a, b in zip(times, times[1:]) if b > a)
        typical = steps[len(steps) // 2] if steps else 0.2
        interval = max(interval, typical)
        for rec in log.records:
            total += 1
            f, t = rec.frame, rec.time
            rpm = defs.value(f, "RPM")
            dt = typical if prev is None else t - prev.time
            if implausible(defs, f, prev.frame if prev else None, dt):
                excluded["implausible reading"] += 1
                last_event = t
                continue  # and don't compare the next record with this one
            # Transient: a jump in RPM or load, or a gap in the log.
            if prev is None or dt <= 0 or dt > settings.max_gap:
                last_event = t
            else:
                d_rpm = abs(rpm - defs.value(prev.frame, "RPM")) / dt
                d_load = max(abs(defs.value(f, cyls[k].load) - defs.value(prev.frame, cyls[k].load))
                             for k in cylinders) / dt
                if d_rpm > settings.rpm_rate or d_load > settings.load_rate:
                    last_event = t
            prev = rec
            weight = min(max(dt, 0.0), settings.max_gap)

            running = defs.bit(f, "Flags1", RUNNING) and rpm >= 500
            if running:
                for key in cylinders:
                    cyl = cyls[key]
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

            # A working narrowband sensor keeps switching between rich and lean in closed loop.
            if running and closed and defs.value(f, "TE") >= settings.min_te:
                if prev_cl is not None and 0 < t - prev_cl.time <= settings.max_gap:
                    o2_seconds += t - prev_cl.time
                    if defs.bit(f, "Flags2", O2_RICH) != defs.bit(prev_cl.frame, "Flags2", O2_RICH):
                        o2_switches += 1
                prev_cl = rec
            else:
                prev_cl = None

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
                usable_seconds += weight
                egos = {}
                for key in cylinders:
                    cyl = cyls[key]
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
    if "front" in results and used and not shared:
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
        # With one AFV for both maps, warn about it once.
        lo_hi = None if shared and key == "front" and "rear" in results else res.afv_range
        if lo_hi and (abs(lo_hi[0] - 100) > 0.05 or abs(lo_hi[1] - 100) > 0.05):
            warnings.append(f"{key}: the AFV wasn't locked at 100 % during the ride "
                            f"({lo_hi[0]:.1f}-{lo_hi[1]:.1f} %). The corrections include it, "
                            "but lock it for cleaner data (docs/egotune-howto.md, step 1).")
        if lo_hi and res.image_afv is not None and abs(res.image_afv - lo_hi[0]) > 0.5 \
                and abs(lo_hi[1] - lo_hi[0]) <= 0.5:
            if res.lookup.spread is not None and res.lookup.spread < 0.01:
                warnings.append(f"{key}: the image stores an AFV of {res.image_afv:.1f} %, the log shows "
                                f"{lo_hi[0]:.1f} %. The maps match the log, so the AFV changed since the "
                                "image was saved: lock it (docs/egotune-howto.md, step 1).")
            else:
                warnings.append(f"{key}: the image stores an AFV of {res.image_afv:.1f} %, the log shows "
                                f"{lo_hi[0]:.1f} %. Was this image in the ECM during the ride?")
    if setup["KLFuel_Max"] is not None and (setup["KLFuel_Max"] != 100 or setup["KLFuel_Min"] != 100):
        warnings.append(f"The image's AFV limits are {setup['KLFuel_Min']:g}-{setup['KLFuel_Max']:g} %, "
                        "not locked at 100 %.")

    summaries = [LogSummary(log.name, log.ecm_id, len(log.records), log.bad_checksum, log.duration)
                 for log in logs]
    return Analysis(img.ecm_id, settings, summaries, total, used, excluded, results, setup, warnings, shared,
                    usable_seconds, interval, o2_seconds, o2_switches)
