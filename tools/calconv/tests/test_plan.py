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
"""Layout analysis. The counts are the ones in docs/calibration-converter.md;
if a database update changes them, update the document too."""

import unittest

from calconvlib.analysis import coverage, make_plan

from .support import db, rules


def plan(src, dst):
    return make_plan(db(), src, dst, rules())


class TestFirstCase(unittest.TestCase):
    """BUE2D -> BUEYD, the first supported conversion."""

    @classmethod
    def setUpClass(cls):
        cls.p = plan("BUE2D", "BUEYD")

    def test_counts(self):
        p = self.p
        self.assertEqual((544, 533), (len(p.src.vars), len(p.dst.vars)))
        self.assertEqual(527, len(p.shared))
        self.assertEqual(42, p.same_offset)
        self.assertEqual(517, len(p.identical))
        self.assertEqual(10, len(p.different))
        self.assertEqual(495, len(p.copyable))
        self.assertEqual(17, len(p.src_only))
        self.assertEqual(6, len(p.dst_only))
        self.assertEqual({}, p.candidates)

    def test_exclusions(self):
        reasons = list(self.p.excluded.values())
        self.assertEqual(20, reasons.count("page 0"))
        self.assertEqual(2, reasons.count("identification"))
        self.assertEqual("identification", self.p.excluded["CSR"])
        self.assertEqual("page 0", self.p.excluded["KVIN"])
        for name in self.p.excluded:
            self.assertNotIn(name, self.p.copyable)

    def test_maps_are_copyable(self):
        for name in ("Tab_Fuel_Front", "Tab_Fuel_Rear", "Tab_Spark_Front", "Tab_Spark_Rear",
                     "Tab_Fuel_RPM_Ax", "Tab_Fuel_Load_Ax", "Tab_Spark_RPM_Ax", "Tab_Spark_Load_Ax"):
            self.assertIn(name, self.p.copyable)

    def test_different_definitions(self):
        expected = {"Tab_Idle_Spark", "KPIF1"} | {f"Tab_{k}{s}" for k in ("P", "I") for s in ("RF", "LF", "RR", "LR")}
        self.assertEqual(expected, set(self.p.different))

    def test_idle_spark_meaning_is_flagged(self):
        self.assertEqual(["Tab_Idle_Spark"], list(self.p.semantic))
        self.assertIn("early DDFI-3 (BUEOD ... BUEZD)", self.p.semantic["Tab_Idle_Spark"])

    def test_lost_features(self):
        for name in ("KSpark_Config", "Tab_Idle_Spark_Front", "Tab_VS_Fan_On", "KNCRPM_Soft_Hi", "Cal_ID"):
            self.assertIn(name, self.p.src_only)
        self.assertEqual({"KTA_F1", "Tab_Fuel_End_SL", "Tab_Fuel_End_Load_Ax", "Tab_Fuel_End_RPM_Ax",
                          "PC_Run_Stat", "AMC_KO_Stat"}, set(self.p.dst_only))

    def test_bitfields(self):
        self.assertEqual(42, len(self.p.bitfields))
        self.assertEqual(26, len(self.p.bitfields_undescribed))
        self.assertEqual([3, 4, 5, 6, 7, 8], self.p.bitfields_undescribed["KEng_Ref"])

    def test_database_warnings(self):
        src = "\n".join(self.p.warnings["BUE2D"])
        self.assertIn("KPIF1: elements column says 6, but 4 bytes hold 4", src)
        self.assertIn("Tab_PRF: elements column says 4, but 5 bytes hold 5", src)
        self.assertIn("Tab_Idle_Spark: 4×4 cells", "\n".join(self.p.warnings["BUEYD"]))

    def test_model_guard(self):
        self.assertIn("KEng_Ref", self.p.model_guard)


class TestOtherPairs(unittest.TestCase):
    def test_counts(self):
        # source, target: source vars, target vars, shared, identical, same offset, source only, target only
        cases = {
            ("BUEYD", "BUE2D"): (533, 544, 527, 517, 42, 6, 17),
            ("BUEZD", "BUE2D"): (539, 544, 532, 520, 76, 7, 12),
            ("BUEWD", "BUE2D"): (519, 544, 506, 489, 42, 13, 38),
            ("BUE1D", "BUE2D"): (537, 544, 534, 523, 76, 3, 10),
            ("BUEOD", "BUE2D"): (412, 544, 386, 374, 37, 26, 158),
            ("BUE2D", "BUE3D"): (544, 662, 533, 472, 502, 11, 129),
            ("BUEGB", "BUEIB"): (233, 241, 233, 231, 124, 0, 8),
        }
        for (src, dst), expected in cases.items():
            p = plan(src, dst)
            got = (len(p.src.vars), len(p.dst.vars), len(p.shared), len(p.identical), p.same_offset,
                   len(p.src_only), len(p.dst_only))
            self.assertEqual(expected, got, f"{src} -> {dst}")

    def test_same_layout(self):
        p = plan("BUE2D", "B3R2D")
        self.assertTrue(p.same_layout)
        self.assertEqual(len(p.src.vars), len(p.identical))

    def test_different_family(self):
        self.assertFalse(plan("BUEIB", "BUE2D").same_family)

    def test_rename_candidates(self):
        def top(src, dst, name):
            return plan(src, dst).candidates[name][0].target

        self.assertEqual("KFan_Period", top("BUEIB", "BUECB", "K_Fan_Period"))
        self.assertEqual("Tab_Fuel_End_TP", top("BUE3D", "BUE2D", "Tab_Fuel_End_Load"))
        self.assertEqual("LFuel1_LD", top("BUE2D", "BUEOD", "LFuel1"))

    def test_skipped_bytes_in_ddfi2_fuel_maps(self):
        # 13 RPM columns plus one skipped byte per row, 12 rows = 168 bytes.
        warnings = "\n".join(plan("BUEGB", "BUEIB").warnings["BUEIB"])
        self.assertNotIn("Tab_Fuel_Front", warnings)
        self.assertIn("Tab_Fuel_Cut: elements column says 156", warnings)

    def test_coverage(self):
        self.assertEqual((3175, 3272), coverage(db().layout("BUEYD")))
        self.assertEqual((3175, 3796), coverage(db().layout("BUE2D")))


if __name__ == "__main__":
    unittest.main()
