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
"""The checks that block apply, and the per-cell limits, each against a faulty log."""

import unittest

from tests.support import COL_3400, ROW_30, defs, frame, image, make_log, ride

from egotunelib.analysis import analyse
from egotunelib.checks import NAMES, run_checks
from egotunelib.tune import BASELINE_LIMIT, NOISY, OUTLIER, propose_all

NEIGHBOURS = ((3400, 30), (2900, 30), (3400, 25))  # a cell and two of its neighbours


def checks_for(frames, step=0.2, accept=(), baselines=None):
    a = analyse(image(), defs(), [make_log(frames, step)])
    changes = propose_all(a, baselines)
    return a, changes, {c.name: c for c in run_checks(a, changes, accept)}


class ChecksTest(unittest.TestCase):
    def test_healthy_ride_passes(self):
        _, _, checks = checks_for(ride(6 * 60, NEIGHBOURS))
        self.assertEqual(set(checks), set(NAMES))
        for c in checks.values():
            self.assertTrue(c.passed, f"{c.name}: {c.measured}")

    def test_short_log(self):
        _, _, checks = checks_for(ride(2 * 60))
        self.assertFalse(checks["short-log"].passed)
        self.assertTrue(checks["short-log"].blocking)

    def test_slow_interval(self):
        _, _, checks = checks_for(ride(6 * 60, step=1.0), step=1.0)
        self.assertFalse(checks["slow-interval"].passed)

    def test_stuck_o2_sensor(self):
        _, _, checks = checks_for(ride(6 * 60, Flags2=0b10000000))  # never reads rich
        self.assertFalse(checks["o2-switching"].passed)

    def test_ego_at_its_limit(self):
        _, _, checks = checks_for(ride(6 * 60, ego=200.0))  # KFBFuel_Max of the test image
        self.assertFalse(checks["ego-limit"].passed)

    def test_implausible_readings(self):
        frames = ride(6 * 60)
        for i in range(0, len(frames), 20):  # 5 %: RPM spikes no engine can do
            frames[i] = frame(RPM=12000)
        a, _, checks = checks_for(frames)
        self.assertFalse(checks["implausible"].passed)
        self.assertEqual(a.excluded["implausible reading"], len(range(0, len(frames), 20)))

    def test_global_offset(self):
        _, _, checks = checks_for(ride(6 * 60, NEIGHBOURS, ego=112.0))
        self.assertFalse(checks["global-offset"].passed)
        self.assertIn("exhaust leak", checks["global-offset"].advice)

    def test_wrong_image(self):
        frames = ride(6 * 60, NEIGHBOURS)
        for i in range(0, len(frames), 2):
            frames[i] = frame(**{**dict(zip(("RPM", "RLoad"), NEIGHBOURS[0])), "TabFuel2_Raw": 2500})
        _, _, checks = checks_for(frames)
        self.assertFalse(checks["lookup"].passed)

    def test_accept_lets_a_check_through(self):
        _, _, checks = checks_for(ride(2 * 60), accept=("short-log",))
        self.assertFalse(checks["short-log"].passed)
        self.assertTrue(checks["short-log"].accepted)
        self.assertFalse(checks["short-log"].blocking)


class CellLimitsTest(unittest.TestCase):
    def cell(self, a):
        return a.cylinders["rear"].fuel_map.index(ROW_30, COL_3400)

    def test_outlier_skipped(self):
        ego = lambda i: 125.0 if i < 600 else 100.0  # the first point (the cell) reads far off
        a, ch, _ = checks_for(ride(6 * 60, NEIGHBOURS, ego=ego))
        c = ch["rear"].cells[self.cell(a)]
        self.assertEqual((c.state, c.new, c.old), (OUTLIER, 45, 45))

    def test_noisy_skipped(self):
        a, ch, _ = checks_for(ride(6 * 60, ego=lambda i: (80.0, 125.0)[i % 2]))
        c = ch["rear"].cells[self.cell(a)]
        self.assertEqual((c.state, c.new), (NOISY, 45))

    def test_baseline_limit(self):
        img = image()
        a = analyse(img, defs(), [make_log(ride(6 * 60, ego=118.0))])
        rear = list(img.physical(img.var("Tab_Fuel_Rear")))
        rear[self.cell(a)] = 39  # the original tune had 39 here: +15 % is 44, the cell is at 45 already
        ch = propose_all(a, {"rear": rear})
        c = ch["rear"].cells[self.cell(a)]
        self.assertEqual((c.state, c.new), (BASELINE_LIMIT, 45))  # held, never pushed leaner
        checks = {c.name: c for c in run_checks(a, ch)}
        self.assertFalse(checks["baseline"].passed)

    def test_baseline_stops_at_the_band(self):
        img = image()
        a = analyse(img, defs(), [make_log(ride(6 * 60, ego=118.0))])
        rear = list(img.physical(img.var("Tab_Fuel_Rear")))
        rear[self.cell(a)] = 40  # +15 % is 46; the correction wants 48
        c = propose_all(a, {"rear": rear})["rear"].cells[self.cell(a)]
        self.assertEqual((c.state, c.new), (BASELINE_LIMIT, 46))


if __name__ == "__main__":
    unittest.main()
