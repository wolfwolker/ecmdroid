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
"""Folding the learned AFV into the fuel maps."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.support import BUE2D_IMAGE, BUEIB_IMAGE, db, image

from calconvlib.image import Image, load_image
from egotunelib.cli import main
from egotunelib.fold import build_fold_image, plan_fold, warnings_for
from egotunelib.fuelmap import MapError, load_fuel_map


def with_value(img, name, raw):
    var = img.var(name)
    start = img.start(var)
    data = bytearray(img.data)
    data[start:start + var.size] = raw.to_bytes(var.size, "little")
    return Image(img.ecm_id, img.layout, bytes(data), None)


def changed_bytes(a, b):
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


class FoldTest(unittest.TestCase):
    def test_ddfi3_rear_afv(self):
        img = image()  # BUE2D: rear AFV 87.9 %, front 100 %
        folds = {f.map_name: f for f in plan_fold(img)}
        rear, front = folds["Tab_Fuel_Rear"], folds["Tab_Fuel_Front"]
        self.assertEqual((rear.afv_name, rear.afv, front.afv_name, front.afv), ("LFuel", 87.9, "LFuel1", 100.0))
        self.assertEqual(front.changed, [])
        fmap = load_fuel_map(img, "Tab_Fuel_Rear")
        used = set(fmap.cells_in_use())
        for i in used:
            self.assertEqual(rear.new[i], round(fmap.values[i] * 0.879))
        self.assertTrue(all(rear.new[i] == fmap.values[i] for i in range(len(fmap.values)) if i not in used))
        out = Image(img.ecm_id, img.layout, build_fold_image(img, list(folds.values())), None)
        self.assertEqual(round(out.value_of("LFuel"), 3), 100)
        self.assertEqual(round(out.value_of("LFuel1"), 3), 100)
        allowed = set()
        for name in ("Tab_Fuel_Rear", "LFuel"):
            start = img.start(img.var(name))
            allowed |= set(range(start, start + img.var(name).size))
        self.assertTrue(set(changed_bytes(img.data, out.data)) <= allowed)

    def test_ddfi2_one_afv_for_both_maps(self):
        img = with_value(load_image(db(), BUEIB_IMAGE, "BUEIB"), "LFuel", 970)
        folds = plan_fold(img)
        self.assertEqual({(f.afv_name, f.afv) for f in folds}, {("LFuel", 97.0)})
        out = build_fold_image(img, folds)
        for f in folds:
            self.assertTrue(f.changed)
            start = img.start(img.var(f.map_name))
            for i in range(13, 168, 14):  # the unused byte at the end of each row
                self.assertEqual(img.data[start + i], out[start + i])

    def test_refuses_a_cell_above_the_maximum(self):
        img = load_image(db(), BUEIB_IMAGE, "BUEIB")  # LFuel 108 %, and cells at 255 already
        with self.assertRaises(MapError) as e:
            plan_fold(img)
        self.assertIn("above the map's maximum of 255", str(e.exception))

    def test_front_afv_needs_page0(self):
        img = image()
        epr = Image(img.ecm_id, img.layout, img.data[:img.layout.size], None)
        with self.assertRaises(MapError):
            plan_fold(epr)

    def test_warnings(self):
        img = image()
        self.assertTrue(any("more than 10 %" in w for w in warnings_for(img, plan_fold(img))))  # 87.9 %
        limit = with_value(img, "LFuel", 600)  # 60 %: KLFuel_Min of the test image
        self.assertTrue(any("learning limit" in w for w in warnings_for(limit, plan_fold(limit))))
        ok = with_value(img, "LFuel", 1030)
        self.assertEqual(warnings_for(ok, plan_fold(ok)), [])


class FoldCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_writes_the_folded_image(self):
        result = self.dir / "iter0.xpr"
        code, out, err = self.call("fold-afv", "--image", BUE2D_IMAGE, "--out", result)
        self.assertEqual(code, 0, err)
        self.assertIn("| `Tab_Fuel_Rear` | 87.9 % (`LFuel`)", out)
        self.assertIn("calconv diff", out)
        img = load_image(db(), result, "BUE2D")
        self.assertEqual(round(img.value_of("LFuel"), 3), 100)
        code, _, err = self.call("fold-afv", "--image", BUE2D_IMAGE, "--out", result)
        self.assertEqual(code, 2)
        self.assertIn("--force", err)

    def test_nothing_to_fold(self):
        folded = self.dir / "iter0.xpr"
        self.assertEqual(self.call("fold-afv", "--image", BUE2D_IMAGE, "--out", folded)[0], 0)
        again = self.dir / "again.xpr"
        code, out, _ = self.call("fold-afv", "--image", folded, "--out", again)
        self.assertEqual(code, 0)
        self.assertIn("Nothing to fold", out)
        self.assertFalse(again.exists())

    def test_refuses_to_overwrite_the_image(self):
        copy = self.dir / "ecm.xpr"
        copy.write_bytes(BUE2D_IMAGE.read_bytes())
        code, _, err = self.call("fold-afv", "--image", copy, "--out", copy, "--force")
        self.assertEqual(code, 2)
        self.assertIn("overwrite an input", err)


if __name__ == "__main__":
    unittest.main()
