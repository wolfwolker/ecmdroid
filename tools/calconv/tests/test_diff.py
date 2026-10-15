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
import unittest

from calconvlib.analysis import covered_mask
from calconvlib.diff import CHANGED, EQUAL, MISSING_B, ONLY_A, ONLY_B, diff_images
from calconvlib.image import image_from_bytes, load_image

from .support import BUE2D_IMAGE, db, rules


def modified(img, changes):
    """A copy of an image with {offset: new byte value} applied."""
    data = bytearray(img.data)
    for offset, value in changes.items():
        data[offset] = value
    return image_from_bytes(db(), bytes(data), img.ecm_id)


class TestSameLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = load_image(db(), BUE2D_IMAGE)

    def test_identical(self):
        d = diff_images(self.img, self.img, rules().private)
        self.assertTrue(d.identical)
        self.assertEqual(len(self.img.layout.vars), len(d.by_status(EQUAL)))
        self.assertEqual((0, 0, 0), (d.bytes.pages, d.bytes.page0, d.bytes.uncovered))

    def test_one_map_cell(self):
        var = self.img.var("Tab_Fuel_Front")
        offset = self.img.start(var) + 21
        d = diff_images(self.img, modified(self.img, {offset: self.img.data[offset] + 3}))
        changed = d.by_status(CHANGED)
        self.assertEqual(["Tab_Fuel_Front"], [e.name for e in changed])
        self.assertEqual([21], changed[0].changed_cells)
        self.assertEqual(1, d.bytes.pages)
        self.assertFalse(d.identical)

    def test_byte_outside_any_variable(self):
        mask = covered_mask(self.img.layout)
        offset = next(i for i, covered in enumerate(mask) if not covered)
        d = diff_images(self.img, modified(self.img, {offset: self.img.data[offset] ^ 0xFF}))
        self.assertEqual([], d.by_status(CHANGED))
        self.assertEqual([offset], d.bytes.uncovered_offsets)
        self.assertFalse(d.identical)

    def test_small_change_in_a_large_value(self):
        # KVIN is an 8-byte number; a float comparison would miss a change of 1.
        var = self.img.var("KVIN")
        offset = self.img.start(var)
        d = diff_images(self.img, modified(self.img, {offset: self.img.data[offset] ^ 0x01}), rules().private)
        entry = next(e for e in d.entries if e.name == "KVIN")
        self.assertEqual(CHANGED, entry.status)
        self.assertTrue(entry.private)
        self.assertEqual(1, d.bytes.page0)

    def test_image_without_page0(self):
        epr = image_from_bytes(db(), self.img.data[:self.img.layout.size], "BUE2D")
        d = diff_images(self.img, epr)
        missing = {e.name for e in d.by_status(MISSING_B)}
        self.assertIn("KVIN", missing)
        self.assertIsNone(d.bytes.page0)


class TestAcrossLayouts(unittest.TestCase):
    def test_bue2d_against_an_empty_bueyd(self):
        img = load_image(db(), BUE2D_IMAGE)
        empty = image_from_bytes(db(), bytes(db().layout("BUEYD").xsize), "BUEYD")
        d = diff_images(img, empty)
        self.assertEqual(17, len(d.by_status(ONLY_A)))
        self.assertEqual(6, len(d.by_status(ONLY_B)))
        self.assertIsNone(d.bytes)
        idle = next(e for e in d.entries if e.name == "Tab_Idle_Spark")
        self.assertEqual(CHANGED, idle.status)
        self.assertTrue(idle.definition)


if __name__ == "__main__":
    unittest.main()
