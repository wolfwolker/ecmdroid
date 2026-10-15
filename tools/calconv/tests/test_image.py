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

from calconvlib.image import ImageError, ecm_info, format_value, format_values, image_from_bytes, load_image

from .support import BUE2D_IMAGE, BUEIB_IMAGE, db


class TestLoading(unittest.TestCase):
    def test_size_detection(self):
        img = load_image(db(), BUE2D_IMAGE)
        self.assertEqual("BUE2D", img.ecm_id)
        self.assertEqual(["B3R2D"], img.same_layout_ids())
        self.assertTrue(img.has_page0)
        self.assertEqual(".xpr", img.kind)

    def test_ambiguous_size_needs_an_id(self):
        with self.assertRaisesRegex(ImageError, "several layouts"):
            load_image(db(), BUEIB_IMAGE)
        img = load_image(db(), BUEIB_IMAGE, "BUEIB")
        self.assertFalse(img.has_page0)
        self.assertEqual(".epr", img.kind)

    def test_wrong_id(self):
        with self.assertRaisesRegex(ImageError, "doesn't fit BUEYD"):
            load_image(db(), BUE2D_IMAGE, "BUEYD")

    def test_unknown_size(self):
        with self.assertRaisesRegex(ImageError, "no ECM layout has 7 bytes"):
            image_from_bytes(db(), b"\0" * 7)

    def test_page0_variables_missing_from_epr(self):
        img = load_image(db(), BUEIB_IMAGE, "BUEIB")
        kbaro = img.var("KBaro")
        self.assertTrue(kbaro.in_page0)
        self.assertIsNone(img.values(kbaro))


class TestDecodingMatchesTheApp(unittest.TestCase):
    """The expectations of TestVariableProvider and TestECM in the app."""

    @classmethod
    def setUpClass(cls):
        cls.img = load_image(db(), BUEIB_IMAGE, "BUEIB")

    def values(self, name):
        return self.img.values(self.img.var(name))

    def test_scalars(self):
        self.assertEqual([77], self.values("Country_ID"))
        self.assertEqual([6], self.values("KMFG_Year"))
        self.assertEqual([204], self.values("KMFG_Serial"))

    def test_axes(self):
        self.assertEqual([10, 15, 20, 30, 40, 50, 60, 80, 100, 125, 175, 255], self.values("Tab_Fuel_Load_Ax"))
        self.assertEqual([8000, 7000, 6000, 5000, 4000, 3400, 2900, 2400, 1900, 1350, 1000, 800, 0],
                         self.values("Tab_Fuel_RPM_Ax"))

    def test_table(self):
        var = self.img.var("Tab_ABP_Conv")
        self.assertEqual((5, 2), (var.rows, var.cols))
        self.assertEqual([125, 100, 127, 60, 170, 80, 213, 100, 250, 120], self.img.values(var))

    def test_ecm_information(self):
        info = ecm_info(self.img)
        self.assertEqual("204", info["serial_no"])
        self.assertEqual("2006-06-08", info["mfg_date"])  # the app shows 6/8/06
        self.assertEqual("77", info["country_id"])


class TestBUE2D(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = load_image(db(), BUE2D_IMAGE)

    def test_ecm_information(self):
        info = ecm_info(self.img)
        self.assertEqual("S1-M2-V12", info["country_id"])  # Country_ID 255 -> KID_* fields
        self.assertEqual("M39EC322", info["calibration_id"])
        self.assertEqual("50", info["layout_revision"])

    def test_bits(self):
        self.assertEqual([0b1101], self.img.values(self.img.var("KSpark_Config")))

    def test_self_contained_table_uses_axis_scaling(self):
        # Tab_Idle_Spark: engine temperature (axis, translate -40) -> advance (scale 0.25).
        var = self.img.var("Tab_Idle_Spark")
        self.assertEqual([0, 13.0, 18, 5.0, 70, 4.0, 120, 0.0, 160, 0.0, 215, 0.0], self.img.physical(var))
        # The database formats are "0.00" for the axis and "0" for the data.
        self.assertEqual("0.00→13, 18.00→5, 70.00→4, 120.00→0, 160.00→0, 215.00→0",
                         format_values(var, self.img.physical(var)))
        # Fractions of the 0.25° steps aren't hidden by the "0" format.
        self.assertEqual("13.25", format_value(var, 13.25, 1))

    def test_eight_byte_values_stay_exact(self):
        vin = self.img.physical(self.img.var("KVIN"))[0]
        self.assertIsInstance(vin, int)


if __name__ == "__main__":
    unittest.main()
