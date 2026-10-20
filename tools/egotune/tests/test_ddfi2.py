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

    def test_lookup_matches_the_ecm_exactly(self):
        # The ECM logs its own map lookup (TabFuel1/2_Raw = map value x 37.5).
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

    def test_afv_warning_once(self):
        warnings = analysis().warnings
        afv = [w for w in warnings if "stores an AFV" in w]
        self.assertEqual(len(afv), 1)
        self.assertIn("the AFV changed since", afv[0])  # the maps match, so it's not the wrong image

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
