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

import unittest

from tests.support import COL_3400, ROW_30, image

from egotunelib.fuelmap import MapError, load_fuel_map, make_axis


class AxisTest(unittest.TestCase):
    def test_descending_with_padding(self):
        ax = make_axis("rpm", [8000, 6000, 4000, 2000, 0, 0])
        self.assertEqual(ax.used, 4)
        self.assertEqual(ax.order(), [3, 2, 1, 0])
        self.assertEqual(ax.weights(3000), [(3, 0.5), (2, 0.5)])
        self.assertEqual(ax.weights(9000), [(0, 1.0)])
        self.assertEqual(ax.weights(100), [(3, 1.0)])
        self.assertEqual(ax.weights(6000), [(1, 1.0)])

    def test_ascending(self):
        ax = make_axis("load", [10, 20, 40])
        self.assertEqual(ax.weights(15), [(0, 0.5), (1, 0.5)])
        self.assertEqual(ax.weights(30), [(1, 0.5), (2, 0.5)])

    def test_not_monotonic(self):
        with self.assertRaises(MapError):
            make_axis("bad", [10, 30, 20])


class FuelMapTest(unittest.TestCase):
    def test_bue2d_rear(self):
        fmap = load_fuel_map(image(), "Tab_Fuel_Rear")
        self.assertEqual((fmap.cols, fmap.rows), (20, 16))
        self.assertEqual(fmap.rpm.used, 17)  # 3 unused RPM columns
        self.assertEqual(fmap.load.used, 16)
        self.assertEqual(fmap.rpm.values[COL_3400], 3400)
        self.assertEqual(fmap.load.values[ROW_30], 30)
        self.assertEqual(fmap.values[fmap.index(ROW_30, COL_3400)], 45)
        self.assertEqual(len(fmap.cells_in_use()), 16 * 17)

    def test_lookup_and_weights(self):
        fmap = load_fuel_map(image(), "Tab_Fuel_Rear")
        self.assertEqual(fmap.lookup(3400, 30), 45)
        weights = fmap.cell_weights(3150, 27.5)  # between 2900/3400 and 25/30
        self.assertEqual(len(weights), 4)
        self.assertAlmostEqual(sum(w for _, w in weights), 1.0)
        for _, w in weights:
            self.assertAlmostEqual(w, 0.25)

    def test_ddfi1_not_supported(self):
        from calconvlib.image import image_from_bytes
        from tests.support import db
        img = image_from_bytes(db(), bytes(db().layout("BUEKA").size), "BUEKA")
        with self.assertRaises(MapError):
            load_fuel_map(img, "Tab_Fuel_Rear")


if __name__ == "__main__":
    unittest.main()
