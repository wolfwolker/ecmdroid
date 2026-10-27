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
"""DDFI-2 against a real ride: the BUEIB test image and log belong together."""

import unittest
from functools import lru_cache

from tests.support import BUEIB_IMAGE, BUEIB_LOG, db

from calconvlib.db import DEFAULT_DB
from calconvlib.image import load_image
from egotunelib.analysis import analyse
from egotunelib.fuelmap import load_fuel_map
from egotunelib.runtime import load_runtime_defs, parse_log
from egotunelib.tune import build_image, propose_all


def image():
    return load_image(db(), BUEIB_IMAGE, "BUEIB")


@lru_cache(maxsize=None)
def analysis():
    defs = load_runtime_defs(DEFAULT_DB, "BUEIB")
    log = parse_log(BUEIB_LOG.read_bytes(), defs.frame_len)
    return analyse(image(), defs, [log])


class Ddfi2Test(unittest.TestCase):
    def test_map_layout(self):
        fmap = load_fuel_map(image(), "Tab_Fuel_Rear")
        self.assertEqual((fmap.cols, fmap.rows, fmap.skip, fmap.stride), (13, 12, 1, 14))
        self.assertEqual(fmap.rpm.used, 12)  # the 13th RPM breakpoint is 0
        self.assertEqual(fmap.load.used, 12)
        self.assertEqual(len(fmap.cells_in_use()), 144)
        self.assertEqual(fmap.row_col(fmap.index(3, 5)), (3, 5))
        self.assertEqual(fmap.values[fmap.index(0, 0)], 23)
        self.assertEqual(fmap.values[fmap.index(11, 12)], 160)

    def test_lookup_follows_the_ecm(self):
        # The ECM logs its own map lookup (TabFuel1/2_Raw = map value x 37.5). It matches
        # within 0.1 % on 69 % of the records; the rest are sampled while RPM and load move,
        # which the robust spread leaves out.
        for res in analysis().cylinders.values():
            self.assertEqual(res.lookup.samples, 13982)
            self.assertAlmostEqual(res.lookup.ratio, 37.5, places=2)
            self.assertLess(res.lookup.spread, 0.001)

    def test_one_sensor_for_both_maps(self):
        a = analysis()
        self.assertTrue(a.shared_feedback)
        self.assertGreater(a.used, 4000)
        front, rear = a.cylinders["front"], a.cylinders["rear"]
        self.assertTrue(front.active)
        self.assertEqual(front.cells.keys(), rear.cells.keys())
        for i in rear.cells:
            self.assertAlmostEqual(front.cells[i].mean, rear.cells[i].mean)
            self.assertAlmostEqual(front.cells[i].seconds, rear.cells[i].seconds)

    def test_no_afv_warning(self):
        # The image stores 108 %, the ride had 100 %. The maps match the log, so it's the right
        # image, and the AFV doesn't enter the correction anyway.
        a = analysis()
        self.assertFalse([w for w in a.warnings if "AFV" in w])
        self.assertEqual(a.cylinders["rear"].afv_range, (100.0, 100.0))
        self.assertTrue(a.cylinders["rear"].afv_stable(a.settings))

    def test_fuel_equation(self):
        """Pulse width = k x table fuel x CrTA x CrTE x (EGO in closed loop, CrOL x AFV in open loop)
        + CrBat: the EGO correction is the whole closed-loop correction (analysis.py)."""
        defs = load_runtime_defs(DEFAULT_DB, "BUEIB")
        log = parse_log(BUEIB_LOG.read_bytes(), defs.frame_len)
        v = defs.value
        ks = {True: [], False: []}
        for rec in log.records:
            f = rec.frame
            if not defs.bit(f, "Flags1", 0) or v(f, "RPM") < 500 or v(f, "TabFuel2") <= 0:
                continue
            if v(f, "CrAcc") > 0 or any(v(f, n) != 100 for n in ("CrDec", "CrWOT", "CrIdle")):
                continue
            pw = v(f, "Fuel2") - v(f, "CrBat")
            if pw <= 0.3:
                continue
            closed = defs.bit(f, "Flags2", 7)
            corr = v(f, "FBFuel") if closed else v(f, "CrOL") * v(f, "LFuel_LD") / 100
            ks[closed].append(pw / (v(f, "TabFuel2") * v(f, "CrTA") * v(f, "CrTE") * corr / 1e6))
        medians = {cl: sorted(x)[len(x) // 2] for cl, x in ks.items()}
        self.assertGreater(min(len(x) for x in ks.values()), 1000)
        self.assertAlmostEqual(medians[True] / medians[False], 1.0, delta=0.005)

    def test_new_image_keeps_skipped_bytes(self):
        img = image()
        changes = propose_all(analysis())
        self.assertTrue(changes["front"].changed and changes["rear"].changed)
        out = build_image(img, changes)
        for name in ("Tab_Fuel_Front", "Tab_Fuel_Rear"):
            start = img.start(img.var(name))
            for i, (a, b) in enumerate(zip(img.data[start:start + 168], out[start:start + 168])):
                if i % 14 == 13:
                    self.assertEqual(a, b, f"{name}: skipped byte {i} changed")
        changed = [i for i, (a, b) in enumerate(zip(img.data, out)) if a != b]
        ranges = [(img.start(img.var(n)), img.start(img.var(n)) + 168) for n in ("Tab_Fuel_Front", "Tab_Fuel_Rear")]
        self.assertTrue(all(any(lo <= i < hi for lo, hi in ranges) for i in changed))


if __name__ == "__main__":
    unittest.main()
